"""Word and Excel files, read with the standard library.

A .docx becomes a page of HTML, and an .xlsx becomes rows for the table viewer.
Both formats are zip files of XML. What comes across is the content and its
structure: headings, paragraphs, emphasis, lists, tables, links, images,
footnotes, and cell values. Fonts, colors, page layout, charts, and formulas
don't (Excel files show each formula's last calculated value).

Everything here treats the file as untrusted: XML with a DOCTYPE is refused
(Office never writes one, and that's where entity bombs live), every part is
read with a size cap however large the zip claims it is, and the HTML is built
from escaped text with an allow-list of tags and URL schemes. The browser
sanitizes it again before showing it.
"""
from __future__ import annotations

import datetime
import posixpath
import re
import threading
import xml.etree.ElementTree as ET
import zipfile
from html import escape

WORD_EXTS = {"docx", "docm", "dotx", "dotm"}
EXCEL_EXTS = {"xlsx", "xlsm", "xltx", "xltm"}

PART_MAX = 64 * 1024 * 1024        # most XML read from one part of a document
SHEET_XML_MAX = 512 * 1024 * 1024  # a worksheet is streamed, so it may be larger
SHEET_ROWS = 100_000               # rows sent to the browser per sheet
SHEET_COLUMNS = 1_000
IMAGE_MAX = 32 * 1024 * 1024
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
               "bmp": "image/bmp", "webp": "image/webp"}

REL_NAMESPACES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/officeDocument/relationships",  # "Strict" files
)


class OfficeError(ValueError):
    """A file this module can't read, with a message for the user."""


def kind_of(path: str):
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return "docx" if ext in WORD_EXTS else "xlsx" if ext in EXCEL_EXTS else None


# -- reading parts ---------------------------------------------------------

def _name(key: str) -> str:
    """Drop the namespace, keeping r: on relationship attributes (r:id, r:embed)."""
    if key[:1] != "{":
        return key
    namespace, _, local = key[1:].partition("}")
    return "r:" + local if namespace in REL_NAMESPACES else local


def _no_doctype(*_):
    raise OfficeError("This file contains XML that Office doesn't write (a DOCTYPE).")


class _Tree(ET.TreeBuilder):
    """Builds elements with plain names, so <w:p> is just "p"."""

    def start(self, tag, attrs):
        return super().start(_name(tag), {_name(key): value for key, value in attrs.items()})

    def end(self, tag):
        return super().end(_name(tag))

    doctype = staticmethod(_no_doctype)


class _Capped:
    def __init__(self, handle, cap: int, part: str):
        self.handle, self.left, self.part = handle, cap, part

    def read(self, size: int) -> bytes:
        chunk = self.handle.read(min(size, self.left + 1))
        self.left -= len(chunk)
        if self.left < 0:
            raise OfficeError("Part of this file (%s) is too large to show." % self.part)
        return chunk


def _feed(archive: zipfile.ZipFile, part: str, target, cap: int):
    parser = ET.XMLParser(target=target)
    with archive.open(part) as handle:
        source = _Capped(handle, cap, part)
        while True:
            chunk = source.read(1 << 20)
            if not chunk:
                break
            parser.feed(chunk)
    return parser.close()


def _parse(archive: zipfile.ZipFile, part: str):
    """The part as an element tree, or None if the file doesn't have it."""
    if part not in archive.NameToInfo:
        return None
    return _feed(archive, part, _Tree(), PART_MAX)


def _open(real: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(real)
    except (zipfile.BadZipFile, OSError):
        raise OfficeError("This isn't a valid Office file. It may be damaged, password-protected, "
                          "or an older format saved with a newer extension.")


def _rels(archive: zipfile.ZipFile, part: str) -> dict:
    """A part's relationships: id -> (target, external)."""
    folder, name = posixpath.split(part)
    tree = _parse(archive, posixpath.join(folder, "_rels", name + ".rels"))
    out = {}
    for rel in tree.iter("Relationship") if tree is not None else ():
        target = rel.get("Target", "")
        external = rel.get("TargetMode") == "External"
        if not external:
            # Targets are relative to the part's folder, or to the package root with a leading slash.
            joined = target[1:] if target.startswith("/") else posixpath.join(folder, target)
            target = posixpath.normpath(joined)
        out[rel.get("Id")] = (target, external)
    return out


def _on(element) -> bool:
    """A Word toggle such as <w:b/>, which w:val="0" or "false" turns off."""
    return element is not None and element.get("val", "true").lower() not in ("0", "false", "off", "none")


def _child(element, name):
    return element.find(name) if element is not None else None


def _val(element, name, default=None):
    found = _child(element, name)
    return found.get("val", default) if found is not None else default


# -- Word --------------------------------------------------------------------

SAFE_LINK = re.compile(r"^(https?:|mailto:)", re.I)
MONO_FONTS = {"consolas", "courier", "courier new", "menlo", "monaco", "lucida console",
              "source code pro", "cascadia code", "cascadia mono", "fira code", "jetbrains mono"}
OL_TYPES = {"lowerLetter": "a", "upperLetter": "A", "lowerRoman": "i", "upperRoman": "I"}
# Inside a paragraph, these hold text that isn't shown: deleted revisions,
# field codes, and the properties of the paragraph and run themselves.
SKIP_INLINE = {"pPr", "rPr", "del", "moveFrom", "instrText", "delText", "fldData",
               "commentReference", "annotationRef", "proofErr", "lastRenderedPageBreak"}


QUOTE_STYLES = {"quote", "intense quote", "block text"}
CAPTION_STYLES = {"caption", "image caption", "table caption"}
CODE_STYLE = re.compile(r"code|preformatted|plain text|macro text|verbatim")
NO_LIST = (None, {}, {})


class _Word:
    def __init__(self, archive: zipfile.ZipFile):
        self.archive = archive
        self.rels = _rels(archive, "word/document.xml")
        self.styles, self.char_styles = self._styles()
        self.numbering = self._numbering()
        self.notes = {kind: self._notes(kind) for kind in ("footnote", "endnote")}
        self.cited = []         # (kind, id) in the order they're first referenced
        self.counters = {}      # (list definition, level) -> last number used
        self.restarted = set()  # (numId, level) whose start override has been applied
        self.ids = set()        # bookmark ids already placed
        self.in_code = False
        self.part_rels = self.rels

    # -- definitions --

    def _styles(self):
        """Paragraph styles: {"heading", "num", "name", "code"}. Character styles: {"code", "rprs"}."""
        tree = _parse(self.archive, "word/styles.xml")
        raw = {}
        for style in tree.iter("style") if tree is not None else ():
            kind = style.get("type", "paragraph")
            if kind not in ("paragraph", "character"):
                continue
            ppr, rpr = _child(style, "pPr"), _child(style, "rPr")
            outline = _val(ppr, "outlineLvl")
            num = _child(ppr, "numPr")
            fonts = _child(rpr, "rFonts")
            raw[(kind, style.get("styleId"))] = {
                "name": (_val(style, "name") or "").lower(), "based": _val(style, "basedOn"),
                "link": _val(style, "link"), "rpr": rpr,
                "mono": fonts is not None and (fonts.get("ascii") or "").lower() in MONO_FONTS,
                "outline": int(outline) if outline and outline.isdigit() else None,
                "num": (_val(num, "numId"), int(_val(num, "ilvl", "0") or 0)) if num is not None else None,
            }

        def chain(kind, style_id):
            """The style, then the styles it's based on."""
            seen = []
            style = raw.get((kind, style_id))
            while style and len(seen) < 10:
                seen.append(style)
                style = raw.get((kind, style["based"]))
            return seen

        def heading(style):
            match = re.fullmatch(r"heading ?(\d)", style["name"])
            if match:
                return int(match.group(1))
            if style["name"] == "title":
                return 1
            if style["outline"] is not None and style["outline"] < 9:
                return style["outline"] + 1
            return None

        def first(styles, pick):
            return next((found for found in map(pick, styles) if found is not None), None)

        def para_code(style):
            # By name, or by a linked character style in a monospace font. Not by
            # the paragraph font alone: some documents set all their text in one.
            linked = raw.get(("character", style["link"]))
            return True if CODE_STYLE.search(style["name"]) or (linked and linked["mono"]) else None

        paragraphs, characters = {}, {}
        for kind, style_id in raw:
            styles = chain(kind, style_id)
            if kind == "paragraph":
                paragraphs[style_id] = {
                    "heading": first(styles, heading), "num": first(styles, lambda style: style["num"]),
                    "name": styles[0]["name"], "code": bool(first(styles, para_code)),
                }
            else:
                characters[style_id] = {
                    "code": any(style["mono"] or CODE_STYLE.search(style["name"]) for style in styles),
                    "rprs": [style["rpr"] for style in styles if style["rpr"] is not None],
                }
        return paragraphs, characters

    def _numbering(self) -> dict:
        """numId -> (list definition id, {level: (format, start, label pattern such as "%1.%2.")},
        {level: number to restart at})."""
        tree = _parse(self.archive, "word/numbering.xml")
        if tree is None:
            return {}
        abstract = {}
        for definition in tree.iter("abstractNum"):
            levels = {}
            for level in definition.iter("lvl"):
                start = _val(level, "start", "1")
                levels[int(level.get("ilvl", "0"))] = (_val(level, "numFmt", "decimal"),
                                                       int(start) if start.lstrip("-").isdigit() else 1,
                                                       _val(level, "lvlText", ""))
            abstract[definition.get("abstractNumId")] = levels
        out = {}
        for num in tree.iter("num"):
            definition = _val(num, "abstractNumId")
            restarts = {}
            for override in num.iter("lvlOverride"):
                start = _val(override, "startOverride")
                if start and start.isdigit():
                    restarts[int(override.get("ilvl", "0"))] = int(start)
            out[num.get("numId")] = (definition, abstract.get(definition, {}), restarts)
        return out

    def _notes(self, kind: str) -> dict:
        part = "word/%ss.xml" % kind
        tree = _parse(self.archive, part)
        if tree is None:
            return {}
        return {note.get("id"): (note, _rels(self.archive, part))
                for note in tree.iter(kind) if note.get("type") in (None, "normal")}

    # -- blocks --

    def page(self) -> str:
        tree = _parse(self.archive, "word/document.xml")
        if tree is None:
            raise OfficeError("This file has no document in it.")
        body = tree.find("body")
        out = self.blocks(body if body is not None else tree)
        notes = []
        for kind, note_id in self.cited:
            note, rels = self.notes[kind][note_id]
            self.part_rels = rels
            inner = self.blocks(note)
            notes.append('<li id="w-%s-%s">%s</li>' % (kind, escape(note_id), inner))
        if notes:
            out += '<hr><section class="notes"><ol>%s</ol></section>' % "".join(notes)
        return out

    def blocks(self, container) -> str:
        out = []
        lists = []  # open lists: [tag, level, list definition]
        code = []   # lines of a code block, one paragraph each

        def flush():
            while code and not code[-1].strip():
                code.pop()
            if code:
                out.append("<pre><code>%s</code></pre>" % "\n".join(code))
                code.clear()

        for element in container:
            tag = element.tag
            if tag == "p":
                kind, html, num = self.paragraph(element)
                if kind == "code":
                    self.close_lists(out, lists)
                    if code or html.strip():
                        code.append(html)
                    continue
                flush()
                if kind == "item":
                    self.list_item(out, lists, num, html)
                    continue
                self.close_lists(out, lists)
                if html:
                    out.append(html)
                continue
            flush()
            if tag == "tbl":
                self.close_lists(out, lists)
                out.append(self.table(element))
            elif tag in ("sdt", "sdtContent", "customXml", "ins", "moveTo", "smartTag"):
                self.close_lists(out, lists)
                inner = element.find("sdtContent") if tag == "sdt" else element
                if inner is not None:
                    out.append(self.blocks(inner))
            elif tag == "AlternateContent":
                choice = element.find("Choice")
                if choice is not None:
                    out.append(self.blocks(choice))
        flush()
        self.close_lists(out, lists)
        return "".join(out)

    @staticmethod
    def close_lists(out, lists):
        while lists:
            out.append("</li></%s>" % lists.pop()[0])

    def advance(self, num):
        """Count one more item at this list position: (format, its number).

        Word counts per list definition, so separate numIds that share one keep
        counting, unless a numId says to restart.
        """
        num_id, level = num
        definition, levels, restarts = self.numbering.get(num_id, NO_LIST)
        definition = definition or num_id
        fmt, start, _ = levels.get(level, ("decimal", 1, ""))
        key = (definition, level)
        if level in restarts and (num_id, level) not in self.restarted:
            self.restarted.add((num_id, level))
            self.counters[key] = restarts[level] - 1
        number = self.counters.get(key, start - 1) + 1
        self.counters[key] = number
        for other in [other for other in self.counters if other[0] == definition and other[1] > level]:
            del self.counters[other]  # a new item restarts the levels under it
        return fmt, number

    def label(self, num) -> str:
        """The number Word shows before a numbered heading, such as "2.1"."""
        num_id, level = num
        definition, levels, _ = self.numbering.get(num_id, NO_LIST)
        definition = definition or num_id
        fmt, number = self.advance(num)
        pattern = levels.get(level, ("decimal", 1, ""))[2]
        if fmt in ("bullet", "none") or not pattern:
            return ""

        def show(match):
            at = int(match.group(1)) - 1
            fmt_at, start_at, _ = levels.get(at, ("decimal", 1, ""))
            return _list_number(self.counters.get((definition, at), start_at), fmt_at)
        return re.sub(r"%(\d)", show, pattern).strip()

    def list_item(self, out, lists, num, content):
        fmt, number = self.advance(num)
        level = num[1]
        definition = self.numbering.get(num[0], NO_LIST)[0] or num[0]
        tag = "ul" if fmt in ("bullet", "none") else "ol"

        while lists and lists[-1][1] > level:
            out.append("</li></%s>" % lists.pop()[0])
        if lists and lists[-1][1] == level:
            if lists[-1][0] == tag and lists[-1][2] == definition:
                out.append("</li>")
            else:
                out.append("</li></%s>" % lists.pop()[0])
        if not lists or lists[-1][1] < level:
            attrs = ""
            if tag == "ol":
                if fmt in OL_TYPES:
                    attrs += ' type="%s"' % OL_TYPES[fmt]
                if number != 1:
                    attrs += ' start="%d"' % number
            out.append("<%s%s>" % (tag, attrs))
            lists.append([tag, level, definition])
        out.append("<li>" + content)

    def paragraph(self, p):
        """(kind, html, list position) for one paragraph. kind is "block" for
        finished HTML, "item" for a list item's content, or "code" for a line
        of a code block."""
        ppr = p.find("pPr")
        style = self.styles.get(_val(ppr, "pStyle"), {})
        if style.get("code"):
            self.in_code = True
            try:
                line = self.inline(p).replace("<br>", "\n")
            finally:
                self.in_code = False
            return "code", line, None
        num = None
        numpr = _child(ppr, "numPr")
        if numpr is not None:
            num_id = _val(numpr, "numId")
            level = _val(numpr, "ilvl")
            style_num = style.get("num")
            if num_id is None and style_num:
                num_id = style_num[0]
            if level is None:
                level = style_num[1] if style_num else 0
            num = (num_id, int(level)) if num_id not in (None, "0") else None
        elif style.get("num") and style["num"][0] != "0":
            num = style["num"]

        outline = _val(ppr, "outlineLvl")
        level = style.get("heading")
        if outline and outline.isdigit() and int(outline) < 9:
            level = int(outline) + 1
        content = self.inline(p).strip()
        if not content:
            return "block", "", None
        if level:
            label = self.label(num) if num else ""
            if label:
                content = escape(label) + " " + content
            return "block", "<h%d>%s</h%d>" % (min(level, 6), content, min(level, 6)), None
        if num is not None:
            return "item", content, num
        attrs = ""
        align = _val(ppr, "jc")
        if align in ("center", "right", "end"):
            attrs = ' style="text-align:%s"' % ("right" if align == "end" else align)
        name = style.get("name", "")
        if name in QUOTE_STYLES:
            return "block", "<blockquote><p>%s</p></blockquote>" % content, None
        if name == "subtitle":
            attrs += ' class="subtitle"'
        elif name in CAPTION_STYLES:
            attrs += ' class="caption"'
        return "block", "<p%s>%s</p>" % (attrs, content), None

    def inline(self, element) -> str:
        out = []
        for child in element:
            tag = child.tag
            if tag in SKIP_INLINE:
                continue
            if tag == "r":
                out.append(self.run(child))
            elif tag == "hyperlink":
                out.append(self.link(child))
            elif tag == "bookmarkStart":
                name = child.get("name", "")
                if name and name != "_GoBack" and name not in self.ids:
                    self.ids.add(name)
                    out.append('<span id="w-%s"></span>' % escape(name))
            elif tag == "AlternateContent":
                choice = child.find("Choice")
                if choice is not None:
                    out.append(self.inline(choice))
            else:  # smartTag, ins, sdt, fldSimple, customXml...: show what's inside
                inner = child.find("sdtContent") if tag == "sdt" else child
                if inner is not None:
                    out.append(self.inline(inner))
        return "".join(out)

    def link(self, element) -> str:
        text = self.inline(element)
        anchor = element.get("anchor")
        target = self.part_rels.get(element.get("r:id"))
        if anchor:
            return '<a href="#w-%s">%s</a>' % (escape(anchor), text)
        if target and target[1] and SAFE_LINK.match(target[0].strip()):
            return '<a href="%s">%s</a>' % (escape(target[0].strip()), text)
        return text

    def run(self, r) -> str:
        rpr = r.find("rPr")
        pieces = []
        for child in r:
            tag = child.tag
            if tag == "t":
                pieces.append(escape(child.text or ""))
            elif tag == "tab" or tag == "ptab":
                pieces.append("\t" if self.in_code else " ")
            elif tag in ("br", "cr"):
                if child.get("type") != "page":
                    pieces.append("<br>")
            elif tag == "noBreakHyphen":
                pieces.append("‑")
            elif tag in ("drawing", "pict", "object"):
                pieces.append(self.images(child))
            elif tag == "AlternateContent":
                choice = child.find("Choice")
                pieces.append(self.run(choice) if choice is not None else "")
            elif tag in ("footnoteReference", "endnoteReference"):
                kind = tag[:-9]
                note_id = child.get("id")
                if note_id in self.notes[kind]:
                    if (kind, note_id) not in self.cited:
                        self.cited.append((kind, note_id))
                    number = self.cited.index((kind, note_id)) + 1
                    pieces.append('<sup><a href="#w-%s-%s">%d</a></sup>' % (kind, escape(note_id), number))
        html = "".join(pieces)
        if not html:
            return html
        # Direct formatting first, then the character style and the styles it's based on.
        char = self.char_styles.get(_val(rpr, "rStyle"), {})
        layers = ([rpr] if rpr is not None else []) + char.get("rprs", [])

        def prop(name):
            return next((found for found in (layer.find(name) for layer in layers) if found is not None), None)

        if _on(prop("vanish")):
            return ""
        fonts = rpr.find("rFonts") if rpr is not None else None
        mono = char.get("code") or (fonts is not None and (fonts.get("ascii") or "").lower() in MONO_FONTS)
        if mono and not self.in_code:
            html = "<code>%s</code>" % html
        vertical = prop("vertAlign")
        vertical = vertical.get("val") if vertical is not None else None
        if "<sup><a" in html:
            vertical = None  # a note marker is already raised; its style usually raises it again
        if vertical == "superscript":
            html = "<sup>%s</sup>" % html
        elif vertical == "subscript":
            html = "<sub>%s</sub>" % html
        if _on(prop("strike")) or _on(prop("dstrike")):
            html = "<s>%s</s>" % html
        if _on(prop("u")):
            html = "<u>%s</u>" % html
        if _on(prop("i")):
            html = "<em>%s</em>" % html
        if _on(prop("b")):
            html = "<strong>%s</strong>" % html
        return html

    def images(self, element) -> str:
        out = []
        described = next((item.get("descr") or item.get("title") for item in element.iter("docPr")), "") or ""
        width = next((item.get("cx") for item in element.iter("extent")), None)
        found = [(blip.get("r:embed"), blip) for blip in element.iter("blip")]
        found += [(data.get("r:id"), data) for data in element.iter("imagedata")]
        for rel_id, _ in found:
            target = self.part_rels.get(rel_id)
            if not target or target[1]:
                continue  # linked rather than embedded
            ext = target[0].rsplit(".", 1)[-1].lower()
            if ext not in IMAGE_TYPES:
                out.append('<span class="docx-missing">[%s image not shown]</span>' % escape(ext.upper()))
                continue
            size = ""
            if width and width.isdigit() and int(width) > 0:
                size = ' width="%d"' % max(int(width) // 9525, 1)  # EMU to CSS pixels
            out.append('<img data-part="%s" alt="%s"%s>' % (escape(target[0]), escape(described), size))
        return "".join(out)

    def table(self, tbl) -> str:
        rows = []  # [[cell dict]] with grid positions, so vertical merges can find their start
        for tr in [child for child in tbl if child.tag == "tr"]:
            header = _on(_child(tr.find("trPr"), "tblHeader"))
            row = []
            column = 0
            before = _val(tr.find("trPr"), "gridBefore")
            if before and before.isdigit():
                column += int(before)
            for tc in self._cells(tr):
                tcpr = tc.find("tcPr")
                span = _val(tcpr, "gridSpan", "1")
                span = int(span) if span.isdigit() and int(span) > 0 else 1
                merge = _child(tcpr, "vMerge")
                cell = {"column": column, "span": span, "rows": 1, "header": header, "tc": tc,
                        "continues": merge is not None and merge.get("val", "continue") == "continue"}
                row.append(cell)
                column += span
            rows.append(row)
        for index, row in enumerate(rows):
            for cell in row:
                if cell["continues"]:
                    for above in reversed(rows[:index]):
                        start = next((c for c in above if c["column"] == cell["column"]), None)
                        if start and not start["continues"]:
                            start["rows"] += 1
                            break
                        if not start:
                            break
        out = ['<table>']
        for row in rows:
            cells = []
            for cell in row:
                if cell["continues"]:
                    continue
                tag = "th" if cell["header"] else "td"
                attrs = (' colspan="%d"' % cell["span"] if cell["span"] > 1 else "")
                attrs += (' rowspan="%d"' % cell["rows"] if cell["rows"] > 1 else "")
                cells.append("<%s%s>%s</%s>" % (tag, attrs, self.blocks(cell["tc"]), tag))
            out.append("<tr>%s</tr>" % "".join(cells))
        out.append("</table>")
        return "".join(out)

    @staticmethod
    def _cells(tr):
        for child in tr:
            if child.tag == "tc":
                yield child
            elif child.tag in ("sdt", "customXml"):
                inner = child.find("sdtContent") if child.tag == "sdt" else child
                if inner is not None:
                    yield from _Word._cells(inner)


def docx_page(real: str) -> dict:
    with _open(real) as archive:
        return {"html": _Word(archive).page()}


def docx_image(real: str, part: str):
    """(bytes, content type) for an image embedded in a Word file."""
    ext = part.rsplit(".", 1)[-1].lower()
    if not part.startswith("word/") or ext not in IMAGE_TYPES:
        raise OfficeError("Not an image in this document.")
    with _open(real) as archive:
        if part not in archive.NameToInfo:
            raise OfficeError("Not an image in this document.")
        with archive.open(part) as handle:
            data = _Capped(handle, IMAGE_MAX, part).read(IMAGE_MAX + 1)
    return data, IMAGE_TYPES[ext]


# -- Excel -------------------------------------------------------------------

DATE_FORMATS = set(range(14, 18)) | {22, 27, 30, 36, 50, 57}
TIME_FORMATS = {18, 19, 20, 21, 45, 46, 47}
PERCENT_FORMATS = {9, 10}
CELL_REF = re.compile(r"([A-Za-z]{1,3})(\d+)")


def column_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _column_index(letters: str) -> int:
    index = 0
    for char in letters.upper():
        index = index * 26 + ord(char) - 64
    return index - 1


def _format_kind(code: str):
    """"date", "time", "datetime", "percent", or None for an Excel number format."""
    plain = re.sub(r'"[^"]*"|\\.|_.|\*.', "", code.split(";")[0])
    elapsed = re.search(r"\[(h+|m+|s+)\]", plain, re.I)
    plain = re.sub(r"\[[^\]]*\]", "", plain).lower()
    if "%" in plain:
        return "percent"
    has_date = bool(re.search(r"[dy]", plain))
    has_time = bool(re.search(r"[hs]", plain)) or bool(elapsed)
    if not has_date and not has_time and "m" in plain and not re.search(r"[0#?]", plain):
        has_date = True  # a format like "mmm" is a month
    if has_date and has_time:
        return "datetime"
    return "date" if has_date else "time" if has_time else None


class _Strings:
    """Streams sharedStrings.xml into a list, skipping phonetic hints."""

    def __init__(self):
        self.items, self.text, self.depth_skip, self.inside_t = [], [], 0, False

    def start(self, tag, attrs):
        tag = _name(tag)
        if tag == "si":
            self.text = []
        elif tag == "rPh":
            self.depth_skip += 1
        elif tag == "t" and not self.depth_skip:
            self.inside_t = True

    def end(self, tag):
        tag = _name(tag)
        if tag == "si":
            self.items.append("".join(self.text))
        elif tag == "rPh":
            self.depth_skip -= 1
        elif tag == "t":
            self.inside_t = False

    def data(self, text):
        if self.inside_t:
            self.text.append(text)

    def close(self):
        return self.items

    doctype = staticmethod(_no_doctype)


class _Stop(Exception):
    pass


class _Sheet:
    """Streams one worksheet, keeping only cell values, up to the row cap."""

    def __init__(self, book):
        self.book = book
        self.cells = {}  # row -> {column: text}
        self.row = 0
        self.column = -1
        self.cell = None
        self.value = None
        self.text = []
        self.collect = False
        self.truncated = False
        self.first_row = None
        self.wide = False
        self.inline = []
        self.phonetic = 0

    def start(self, tag, attrs):
        tag = _name(tag)
        if tag == "row":
            number = attrs.get("r")
            self.row = int(number) if number and number.isdigit() else self.row + 1
            self.column = -1
            if self.first_row is not None and self.row - self.first_row >= SHEET_ROWS:
                self.truncated = True
                raise _Stop
        elif tag == "c":
            match = CELL_REF.fullmatch(attrs.get("r", ""))
            if match:
                self.column = _column_index(match.group(1))
                self.row = int(match.group(2))
            else:
                self.column += 1
            self.cell = (attrs.get("t", "n"), attrs.get("s"))
            self.value = None
            self.inline = []
        elif tag == "rPh":
            self.phonetic += 1
        elif tag in ("v", "t") and self.cell is not None and not self.phonetic:
            self.text = []
            self.collect = True

    def data(self, text):
        if self.collect:
            self.text.append(text)

    def end(self, tag):
        tag = _name(tag)
        if tag == "v" and self.cell is not None:
            self.value = "".join(self.text)
            self.collect = False
        elif tag == "rPh":
            self.phonetic -= 1
        elif tag == "t" and self.cell is not None and self.collect:
            self.inline.append("".join(self.text))
            self.collect = False
        elif tag == "c" and self.cell is not None:
            kind, style = self.cell
            raw = "".join(self.inline) if kind == "inlineStr" else self.value
            text = self.book.display(kind, style, raw)
            self.cell = None
            if text == "":
                return
            if self.column >= SHEET_COLUMNS:
                self.wide = True
                return
            if self.first_row is None:
                self.first_row = self.row
            self.cells.setdefault(self.row, {})[self.column] = text

    def close(self):
        return None

    doctype = staticmethod(_no_doctype)


class _Book:
    def __init__(self, archive: zipfile.ZipFile):
        self.archive = archive
        workbook = _parse(archive, "xl/workbook.xml")
        if workbook is None:
            raise OfficeError("This file has no workbook in it.")
        rels = _rels(archive, "xl/workbook.xml")
        self.sheets = []
        for sheet in workbook.iter("sheet"):
            target = rels.get(sheet.get("r:id"))
            if target and not target[1]:
                self.sheets.append({"name": sheet.get("name", "Sheet"), "part": target[0],
                                    "hidden": sheet.get("state", "visible") != "visible"})
        view = next(workbook.iter("workbookView"), None)
        active = view.get("activeTab", "0") if view is not None else "0"
        self.active = int(active) if active.isdigit() and int(active) < len(self.sheets) else 0
        pr = next(workbook.iter("workbookPr"), None)
        flag = (pr.get("date1904", "0") if pr is not None else "0").lower()
        self.epoch = datetime.datetime(1904, 1, 1) if flag in ("1", "true") else datetime.datetime(1899, 12, 30)
        self.strings = []
        if "xl/sharedStrings.xml" in archive.NameToInfo:
            self.strings = _feed(archive, "xl/sharedStrings.xml", _Strings(), SHEET_XML_MAX)
        self.formats = self._formats()

    def _formats(self) -> list:
        """The kind of value each cell style shows, indexed by the cell's s attribute."""
        tree = _parse(self.archive, "xl/styles.xml")
        if tree is None:
            return []
        custom = {}
        for fmt in tree.iter("numFmt"):
            code = fmt.get("numFmtId", "")
            if code.isdigit():
                custom[int(code)] = _format_kind(fmt.get("formatCode", ""))
        kinds = []
        xfs = tree.find("cellXfs")
        for xf in xfs.iter("xf") if xfs is not None else ():
            code = xf.get("numFmtId", "0")
            code = int(code) if code.isdigit() else 0
            if code in custom:
                kinds.append(custom[code])
            elif code in DATE_FORMATS:
                kinds.append("date")
            elif code in TIME_FORMATS:
                kinds.append("time")
            elif code in PERCENT_FORMATS:
                kinds.append("percent")
            else:
                kinds.append(None)
        return kinds

    def display(self, kind: str, style, raw) -> str:
        if raw is None:
            return ""
        if kind == "s":
            try:
                return self.strings[int(raw)]
            except (ValueError, IndexError):
                return ""
        if kind in ("str", "inlineStr", "e", "d"):
            return raw
        if kind == "b":
            return "TRUE" if raw.strip() == "1" else "FALSE"
        try:
            number = float(raw)
        except ValueError:
            return raw
        shown = self.formats[int(style)] if style and style.isdigit() and int(style) < len(self.formats) else None
        if shown in ("date", "datetime", "time") and -1 < number < 2958466:
            moment = self.epoch + datetime.timedelta(days=number)
            moment = moment.replace(microsecond=0) + datetime.timedelta(seconds=round(moment.microsecond / 1e6))
            if shown == "time":
                return moment.strftime("%H:%M:%S")
            if shown == "datetime" or moment.time() != datetime.time(0):
                return moment.strftime("%Y-%m-%d %H:%M:%S" if moment.second else "%Y-%m-%d %H:%M")
            return moment.strftime("%Y-%m-%d")
        if shown == "percent":
            return _number(number * 100) + "%"
        return _number(number)

    def sheet(self, index: int) -> dict:
        info = self.sheets[index]
        reader = _Sheet(self)
        if info["part"] in self.archive.NameToInfo:
            try:
                _feed(self.archive, info["part"], reader, SHEET_XML_MAX)
            except _Stop:
                pass
        cells = reader.cells
        if not cells:
            return {"rows": [], "first_row": 1, "first_col": 0, "truncated": False}
        first_row = min(cells)
        last_row = max(cells)
        first_col = min(min(row) for row in cells.values())
        rows = []
        for number in range(first_row, last_row + 1):
            found = cells.get(number)
            if not found:
                rows.append([])
                continue
            row = [""] * (max(found) - first_col + 1)
            for column, text in found.items():
                row[column - first_col] = text
            rows.append(row)
        return {"rows": rows, "first_row": first_row, "first_col": first_col,
                "truncated": reader.truncated, "wide": reader.wide}


def _list_number(number: int, fmt: str) -> str:
    if fmt in ("lowerLetter", "upperLetter") and number > 0:
        text = column_letters(number - 1)
        return text.lower() if fmt == "lowerLetter" else text
    if fmt in ("lowerRoman", "upperRoman") and 0 < number < 4000:
        text = ""
        for value, letters in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                               (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
            while number >= value:
                text += letters
                number -= value
        return text.lower() if fmt == "lowerRoman" else text
    return str(number)


def _number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return "%.15g" % value


def xlsx_sheet(real: str, sheet=None) -> dict:
    with _open(real) as archive:
        book = _Book(archive)
        if not book.sheets:
            raise OfficeError("This workbook has no sheets.")
        index = book.active
        if sheet is not None:
            try:
                index = int(sheet)
            except ValueError:
                index = -1
            if not 0 <= index < len(book.sheets):
                raise OfficeError("This workbook has no sheet %s." % sheet)
        out = book.sheet(index)
    out["sheets"] = [{"name": item["name"], "hidden": item["hidden"]} for item in book.sheets]
    out["sheet"] = index
    out["first_letter"] = column_letters(out["first_col"])
    return out


# -- entry point -------------------------------------------------------------

class Office:
    """Converts files for the API, remembering the last few results."""

    KEEP = 8

    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}  # (real, sheet) -> (mtime, size, result)

    def read(self, real: str, mtime: float, size: int, sheet=None) -> dict:
        kind = kind_of(real)
        if kind is None:
            raise OfficeError("Not a Word or Excel file.")
        key = (real, sheet if kind == "xlsx" else None)
        with self.lock:
            hit = self.cache.get(key)
        if hit and hit[:2] == (mtime, size):
            return hit[2]
        with _errors():
            result = docx_page(real) if kind == "docx" else xlsx_sheet(real, sheet)
        result = dict(result, type=kind)
        with self.lock:
            self.cache[key] = (mtime, size, result)
            while len(self.cache) > self.KEEP:
                self.cache.pop(next(iter(self.cache)))
        return result

    def image(self, real: str, part: str):
        if kind_of(real) != "docx":
            raise OfficeError("Not a Word file.")
        with _errors():
            return docx_image(real, part)


class _errors:
    """Turns the ways a damaged file fails into an OfficeError."""

    def __enter__(self):
        return self

    def __exit__(self, kind, error, trace):
        if kind is None or issubclass(kind, OfficeError):
            return False
        if issubclass(kind, ET.ParseError):
            raise OfficeError("This file's XML is damaged, so it can't be shown.") from error
        if issubclass(kind, (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, EOFError, OSError,
                             RuntimeError, NotImplementedError, ValueError, IndexError)):
            raise OfficeError("This file couldn't be read. It may be damaged or encrypted.") from error
        return False
