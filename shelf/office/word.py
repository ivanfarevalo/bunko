"""Word documents (.docx) as HTML.

Shows headings, paragraphs, emphasis, lists, tables, links, images, footnotes,
quotes, captions, and code. Leaves out fonts, colors, page layout, headers and
footers, comments, and text boxes. The HTML is built from escaped text with an
allow-list of tags and link schemes; the browser sanitizes it again.
"""

from __future__ import annotations

import re
import zipfile
from html import escape

from .common import (
    CappedReader,
    OfficeError,
    child_val,
    find_child,
    letters,
    open_package,
    parse_part,
    relationships,
    toggled,
)

IMAGE_MAX = 32 * 1024 * 1024
IMAGE_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "webp": "image/webp",
}


SAFE_LINK = re.compile(r"^(https?:|mailto:)", re.I)
MONO_FONTS = {
    "consolas",
    "courier",
    "courier new",
    "menlo",
    "monaco",
    "lucida console",
    "source code pro",
    "cascadia code",
    "cascadia mono",
    "fira code",
    "jetbrains mono",
}
OL_TYPES = {"lowerLetter": "a", "upperLetter": "A", "lowerRoman": "i", "upperRoman": "I"}
# Inside a paragraph, these hold text that isn't shown: deleted revisions,
# field codes, and the properties of the paragraph and run themselves.
SKIP_INLINE = {
    "pPr",
    "rPr",
    "del",
    "moveFrom",
    "instrText",
    "delText",
    "fldData",
    "commentReference",
    "annotationRef",
    "proofErr",
    "lastRenderedPageBreak",
}


QUOTE_STYLES = {"quote", "intense quote", "block text"}
CAPTION_STYLES = {"caption", "image caption", "table caption"}
CODE_STYLE = re.compile(r"code|preformatted|plain text|macro text|verbatim")
NO_LIST = (None, {}, {})


class _Word:
    def __init__(self, archive: zipfile.ZipFile):
        self.archive = archive
        self.rels = relationships(archive, "word/document.xml")
        self.styles, self.char_styles = self._styles()
        self.numbering = self._numbering()
        self.notes = {kind: self._notes(kind) for kind in ("footnote", "endnote")}
        self.cited = []  # (kind, id) in the order they're first referenced
        self.counters = {}  # (list definition, level) -> last number used
        self.restarted = set()  # (numId, level) whose start override has been applied
        self.ids = set()  # bookmark ids already placed
        self.in_code = False
        self.part_rels = self.rels

    # -- definitions --

    def _styles(self):
        """Paragraph styles: {"heading", "num", "name", "code"}. Character styles: {"code", "rprs"}."""
        tree = parse_part(self.archive, "word/styles.xml")
        raw = {}
        for style in tree.iter("style") if tree is not None else ():
            kind = style.get("type", "paragraph")
            if kind not in ("paragraph", "character"):
                continue
            ppr, rpr = find_child(style, "pPr"), find_child(style, "rPr")
            outline = child_val(ppr, "outlineLvl")
            num = find_child(ppr, "numPr")
            fonts = find_child(rpr, "rFonts")
            raw[(kind, style.get("styleId"))] = {
                "name": (child_val(style, "name") or "").lower(),
                "based": child_val(style, "basedOn"),
                "link": child_val(style, "link"),
                "rpr": rpr,
                "mono": fonts is not None and (fonts.get("ascii") or "").lower() in MONO_FONTS,
                "outline": int(outline) if outline and outline.isdigit() else None,
                "num": (child_val(num, "numId"), int(child_val(num, "ilvl", "0") or 0))
                if num is not None
                else None,
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
                    "heading": first(styles, heading),
                    "num": first(styles, lambda style: style["num"]),
                    "name": styles[0]["name"],
                    "code": bool(first(styles, para_code)),
                }
            else:
                characters[style_id] = {
                    "code": any(
                        style["mono"] or CODE_STYLE.search(style["name"]) for style in styles
                    ),
                    "rprs": [style["rpr"] for style in styles if style["rpr"] is not None],
                }
        return paragraphs, characters

    def _numbering(self) -> dict:
        """numId -> (list definition id, {level: (format, start, label pattern such as "%1.%2.")},
        {level: number to restart at})."""
        tree = parse_part(self.archive, "word/numbering.xml")
        if tree is None:
            return {}
        abstract = {}
        for definition in tree.iter("abstractNum"):
            levels = {}
            for level in definition.iter("lvl"):
                start = child_val(level, "start", "1")
                levels[int(level.get("ilvl", "0"))] = (
                    child_val(level, "numFmt", "decimal"),
                    int(start) if start.lstrip("-").isdigit() else 1,
                    child_val(level, "lvlText", ""),
                )
            abstract[definition.get("abstractNumId")] = levels
        out = {}
        for num in tree.iter("num"):
            definition = child_val(num, "abstractNumId")
            restarts = {}
            for override in num.iter("lvlOverride"):
                start = child_val(override, "startOverride")
                if start and start.isdigit():
                    restarts[int(override.get("ilvl", "0"))] = int(start)
            out[num.get("numId")] = (definition, abstract.get(definition, {}), restarts)
        return out

    def _notes(self, kind: str) -> dict:
        part = f"word/{kind}s.xml"
        tree = parse_part(self.archive, part)
        if tree is None:
            return {}
        return {
            note.get("id"): (note, relationships(self.archive, part))
            for note in tree.iter(kind)
            if note.get("type") in (None, "normal")
        }

    # -- blocks --

    def page(self) -> str:
        tree = parse_part(self.archive, "word/document.xml")
        if tree is None:
            raise OfficeError("This file has no document in it.")
        body = tree.find("body")
        out = self.blocks(body if body is not None else tree)
        notes = []
        for kind, note_id in self.cited:
            note, rels = self.notes[kind][note_id]
            self.part_rels = rels
            inner = self.blocks(note)
            notes.append(f'<li id="w-{kind}-{escape(note_id)}">{inner}</li>')
        if notes:
            items = "".join(notes)
            out += f'<hr><section class="notes"><ol>{items}</ol></section>'
        return out

    def blocks(self, container) -> str:
        out = []
        lists = []  # open lists: [tag, level, list definition]
        code = []  # lines of a code block, one paragraph each

        def flush():
            while code and not code[-1].strip():
                code.pop()
            if code:
                lines = "\n".join(code)
                out.append(f"<pre><code>{lines}</code></pre>")
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
            out.append(f"</li></{lists.pop()[0]}>")

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
        for other in [
            other for other in self.counters if other[0] == definition and other[1] > level
        ]:
            del self.counters[other]  # a new item restarts the levels under it
        return fmt, number

    def label(self, num) -> str:
        """The number Word shows before a numbered heading, such as "2.1"."""
        num_id, level = num
        definition, levels, _ = self.numbering.get(num_id, NO_LIST)
        definition = definition or num_id
        fmt, _ = self.advance(num)
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
            out.append(f"</li></{lists.pop()[0]}>")
        if lists and lists[-1][1] == level:
            if lists[-1][0] == tag and lists[-1][2] == definition:
                out.append("</li>")
            else:
                out.append(f"</li></{lists.pop()[0]}>")
        if not lists or lists[-1][1] < level:
            attrs = ""
            if tag == "ol":
                if fmt in OL_TYPES:
                    attrs += f' type="{OL_TYPES[fmt]}"'
                if number != 1:
                    attrs += f' start="{number}"'
            out.append(f"<{tag}{attrs}>")
            lists.append([tag, level, definition])
        out.append("<li>" + content)

    def paragraph(self, p):
        """(kind, html, list position) for one paragraph. kind is "block" for
        finished HTML, "item" for a list item's content, or "code" for a line
        of a code block."""
        ppr = p.find("pPr")
        style = self.styles.get(child_val(ppr, "pStyle"), {})
        if style.get("code"):
            self.in_code = True
            try:
                line = self.inline(p).replace("<br>", "\n")
            finally:
                self.in_code = False
            return "code", line, None
        num = None
        numpr = find_child(ppr, "numPr")
        if numpr is not None:
            num_id = child_val(numpr, "numId")
            level = child_val(numpr, "ilvl")
            style_num = style.get("num")
            if num_id is None and style_num:
                num_id = style_num[0]
            if level is None:
                level = style_num[1] if style_num else 0
            num = (num_id, int(level)) if num_id not in (None, "0") else None
        elif style.get("num") and style["num"][0] != "0":
            num = style["num"]

        outline = child_val(ppr, "outlineLvl")
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
            tag = f"h{min(level, 6)}"
            return "block", f"<{tag}>{content}</{tag}>", None
        if num is not None:
            return "item", content, num
        attrs = ""
        align = child_val(ppr, "jc")
        if align in ("center", "right", "end"):
            attrs = ' style="text-align:%s"' % ("right" if align == "end" else align)
        name = style.get("name", "")
        if name in QUOTE_STYLES:
            return "block", f"<blockquote><p>{content}</p></blockquote>", None
        if name == "subtitle":
            attrs += ' class="subtitle"'
        elif name in CAPTION_STYLES:
            attrs += ' class="caption"'
        return "block", f"<p{attrs}>{content}</p>", None

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
                    out.append(f'<span id="w-{escape(name)}"></span>')
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
            return f'<a href="#w-{escape(anchor)}">{text}</a>'
        if target and target[1] and SAFE_LINK.match(target[0].strip()):
            return f'<a href="{escape(target[0].strip())}">{text}</a>'
        return text

    def run(self, r) -> str:
        rpr = r.find("rPr")
        pieces = []
        for child in r:
            tag = child.tag
            if tag == "t":
                pieces.append(escape(child.text or ""))
            elif tag == "tab" or tag == "ptab":
                pieces.append("\t" if self.in_code else "\u2003")  # em space
            elif tag in ("br", "cr"):
                if child.get("type") != "page":
                    pieces.append("<br>")
            elif tag == "noBreakHyphen":
                pieces.append("\u2011")  # non-breaking hyphen
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
                    anchor = f"w-{kind}-{escape(note_id)}"
                    pieces.append(f'<sup><a href="#{anchor}">{number}</a></sup>')
        html = "".join(pieces)
        if not html:
            return html
        # Direct formatting first, then the character style and the styles it's based on.
        char = self.char_styles.get(child_val(rpr, "rStyle"), {})
        layers = ([rpr] if rpr is not None else []) + char.get("rprs", [])

        def prop(name):
            return next(
                (found for found in (layer.find(name) for layer in layers) if found is not None),
                None,
            )

        if toggled(prop("vanish")):
            return ""
        fonts = rpr.find("rFonts") if rpr is not None else None
        mono = char.get("code") or (
            fonts is not None and (fonts.get("ascii") or "").lower() in MONO_FONTS
        )
        if mono and not self.in_code:
            html = f"<code>{html}</code>"
        vertical = prop("vertAlign")
        vertical = vertical.get("val") if vertical is not None else None
        if "<sup><a" in html:
            vertical = None  # a note marker is already raised; its style usually raises it again
        if vertical == "superscript":
            html = f"<sup>{html}</sup>"
        elif vertical == "subscript":
            html = f"<sub>{html}</sub>"
        if toggled(prop("strike")) or toggled(prop("dstrike")):
            html = f"<s>{html}</s>"
        if toggled(prop("u")):
            html = f"<u>{html}</u>"
        if toggled(prop("i")):
            html = f"<em>{html}</em>"
        if toggled(prop("b")):
            html = f"<strong>{html}</strong>"
        return html

    def images(self, element) -> str:
        out = []
        described = (
            next((item.get("descr") or item.get("title") for item in element.iter("docPr")), "")
            or ""
        )
        width = next((item.get("cx") for item in element.iter("extent")), None)
        found = [(blip.get("r:embed"), blip) for blip in element.iter("blip")]
        found += [(data.get("r:id"), data) for data in element.iter("imagedata")]
        for rel_id, _ in found:
            target = self.part_rels.get(rel_id)
            if not target or target[1]:
                continue  # linked rather than embedded
            ext = target[0].rsplit(".", 1)[-1].lower()
            if ext not in IMAGE_TYPES:
                out.append(
                    f'<span class="docx-missing">[{escape(ext.upper())} image not shown]</span>'
                )
                continue
            size = ""
            if width and width.isdigit() and int(width) > 0:
                size = f' width="{max(int(width) // 9525, 1)}"'  # EMU to CSS pixels
            out.append(f'<img data-part="{escape(target[0])}" alt="{escape(described)}"{size}>')
        return "".join(out)

    def table(self, tbl) -> str:
        rows = []  # [[cell dict]] with grid positions, so vertical merges can find their start
        for tr in [child for child in tbl if child.tag == "tr"]:
            header = toggled(find_child(tr.find("trPr"), "tblHeader"))
            row = []
            column = 0
            before = child_val(tr.find("trPr"), "gridBefore")
            if before and before.isdigit():
                column += int(before)
            for tc in self._cells(tr):
                tcpr = tc.find("tcPr")
                span = child_val(tcpr, "gridSpan", "1")
                span = int(span) if span.isdigit() and int(span) > 0 else 1
                merge = find_child(tcpr, "vMerge")
                cell = {
                    "column": column,
                    "span": span,
                    "rows": 1,
                    "header": header,
                    "tc": tc,
                    "continues": merge is not None and merge.get("val", "continue") == "continue",
                }
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
        out = ["<table>"]
        for row in rows:
            cells = []
            for cell in row:
                if cell["continues"]:
                    continue
                tag = "th" if cell["header"] else "td"
                attrs = f' colspan="{cell["span"]}"' if cell["span"] > 1 else ""
                attrs += f' rowspan="{cell["rows"]}"' if cell["rows"] > 1 else ""
                cells.append(f"<{tag}{attrs}>{self.blocks(cell['tc'])}</{tag}>")
            row_html = "".join(cells)
            out.append(f"<tr>{row_html}</tr>")
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
    with open_package(real) as archive:
        return {"html": _Word(archive).page()}


def docx_image(real: str, part: str):
    """(bytes, content type) for an image embedded in a Word file."""
    ext = part.rsplit(".", 1)[-1].lower()
    if not part.startswith("word/") or ext not in IMAGE_TYPES:
        raise OfficeError("Not an image in this document.")
    with open_package(real) as archive:
        if part not in archive.NameToInfo:
            raise OfficeError("Not an image in this document.")
        with archive.open(part) as handle:
            data = CappedReader(handle, IMAGE_MAX, part).read(IMAGE_MAX + 1)
    return data, IMAGE_TYPES[ext]


ROMAN = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)  # fmt: skip


def _list_number(number: int, fmt: str) -> str:
    """A list item's number as Word shows it in a label: 3, c, C, iii, or III."""
    if fmt in ("lowerLetter", "upperLetter") and number > 0:
        text = letters(number - 1)
        return text.lower() if fmt == "lowerLetter" else text
    if fmt in ("lowerRoman", "upperRoman") and 0 < number < 4000:
        text = ""
        for value, numeral in ROMAN:
            while number >= value:
                text += numeral
                number -= value
        return text.lower() if fmt == "lowerRoman" else text
    return str(number)
