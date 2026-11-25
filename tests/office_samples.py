"""Small Word and Excel files written from scratch, for tests and the demo tree.

Only what a reader needs is included, laid out the way Word and Excel write it.
"""

import struct
import zipfile
import zlib
from xml.sax.saxutils import escape

W_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
)
S_NS = (
    'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
RELS_NS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def png(width=4, height=3, color=(220, 60, 40)):
    """A solid-color PNG."""
    row = b"\x00" + bytes(color) * width

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


CT = "application/vnd.openxmlformats-officedocument."
CONTENT_DEFAULTS = {
    "rels": "application/vnd.openxmlformats-package.relationships+xml",
    "xml": "application/xml",
    "png": "image/png",
    "emf": "image/x-emf",
    "svg": "image/svg+xml",
}


def _attr(text):
    return escape(text, {'"': "&quot;"})


def _content_types(overrides):
    """[Content_Types].xml, which Word, Excel and LibreOffice need to open the file."""
    defaults = "".join(
        f'<Default Extension="{ext}" ContentType="{kind}"/>'
        for ext, kind in CONTENT_DEFAULTS.items()
    )
    parts = "".join(
        f'<Override PartName="/{part}" ContentType="{CT}{kind}"/>' for part, kind in overrides
    )
    types = "http://schemas.openxmlformats.org/package/2006/content-types"
    return f'{HEAD}<Types xmlns="{types}">{defaults}{parts}</Types>'


def _rels(items):
    external_mode = ' TargetMode="External"'
    body = "".join(
        f'<Relationship Id="{rid}" Type="{REL}{kind}" Target="{_attr(target)}"'
        f"{external_mode if external else ''}/>"
        for rid, kind, target, external in items
    )
    return f"{HEAD}<Relationships {RELS_NS}>{body}</Relationships>"


# -- Word --------------------------------------------------------------------


def p(text="", style=None, num=None, align=None, runs=None):
    """A paragraph. num: (numId, level). runs: XML for the runs, instead of plain text."""
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if num:
        ppr += f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>'
    if align:
        ppr += f'<w:jc w:val="{align}"/>'
    if ppr:
        ppr = f"<w:pPr>{ppr}</w:pPr>"
    return f"<w:p>{ppr}{runs if runs is not None else r(text)}</w:p>"


def r(text, *props, font=None):
    """A run of text. props: run properties such as "b" or 'vertAlign w:val="superscript"'."""
    rpr = "".join(f"<w:{prop}/>" for prop in props)
    if font:
        rpr += f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>'
    if rpr:
        rpr = f"<w:rPr>{rpr}</w:rPr>"
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def table(rows, header=True):
    """rows: lists of cells; a cell is text, or (text, {"span": n, "merge": "restart"|"continue"})."""
    out = []
    for index, row in enumerate(rows):
        cells = []
        for item in row:
            text, opts = (item, {}) if isinstance(item, str) else item
            tcpr = ""
            if opts.get("span"):
                tcpr += f'<w:gridSpan w:val="{opts["span"]}"/>'
            if opts.get("merge") == "restart":
                tcpr += '<w:vMerge w:val="restart"/>'
            elif opts.get("merge") == "continue":
                tcpr += "<w:vMerge/>"
            if tcpr:
                tcpr = f"<w:tcPr>{tcpr}</w:tcPr>"
            cells.append(f"<w:tc>{tcpr}{p(text)}</w:tc>")
        trpr = "<w:trPr><w:tblHeader/></w:trPr>" if header and index == 0 else ""
        out.append(f"<w:tr>{trpr}{''.join(cells)}</w:tr>")
    return f"<w:tbl><w:tblPr/>{''.join(out)}</w:tbl>"


def image(rid, name="Chart", descr="", cx=1905000):
    """An inline picture; cx is its width in EMU."""
    return (
        f'<w:r><w:drawing><wp:inline><wp:extent cx="{cx}" cy="952500"/>'
        f'<wp:docPr id="1" name="{name}" descr="{_attr(descr)}"/><a:graphic><a:graphicData>'
        f'<pic:pic><pic:blipFill><a:blip r:embed="{rid}"/></pic:blipFill></pic:pic>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
    )


STYLES = (
    HEAD
    + f"""<w:styles {W_NS}>
<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="NumberedHeading"><w:name w:val="Numbered Heading"/><w:basedOn w:val="Heading1"/>
  <w:pPr><w:numPr><w:numId w:val="3"/></w:numPr></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/></w:style>
<w:style w:type="paragraph" w:styleId="SourceCode"><w:name w:val="Source Code"/></w:style>
<w:style w:type="paragraph" w:styleId="BlockText"><w:name w:val="Block Text"/></w:style>
<w:style w:type="paragraph" w:styleId="ImageCaption"><w:name w:val="Image Caption"/></w:style>
<w:style w:type="character" w:styleId="VerbatimChar"><w:name w:val="Verbatim Char"/><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Strong"><w:name w:val="Strong"/><w:rPr><w:b/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr></w:style>
</w:styles>"""
)

NUMBERING = (
    HEAD
    + f"""<w:numbering {W_NS}>
<w:abstractNum w:abstractNumId="10">
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl>
  <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="o"/></w:lvl>
</w:abstractNum>
<w:abstractNum w:abstractNumId="11">
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
  <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/></w:lvl>
</w:abstractNum>
<w:abstractNum w:abstractNumId="12">
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
</w:abstractNum>
<w:abstractNum w:abstractNumId="13">
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="10"/></w:num>
<w:num w:numId="2"><w:abstractNumId w:val="11"/></w:num>
<w:num w:numId="3"><w:abstractNumId w:val="12"/></w:num>
<w:num w:numId="5"><w:abstractNumId w:val="13"/></w:num>
<w:num w:numId="6"><w:abstractNumId w:val="13"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>
</w:numbering>"""
)


def write_docx(path, body, rels=(), media=None, footnotes=None, document=None, styles=STYLES):
    """body: XML for the paragraphs and tables. rels: (id, type, target, external)."""
    media = media or {}
    rels = [*list(rels), ("rIdNumbering", "numbering", "numbering.xml", False)]
    rels += [("rIdStyles", "styles", "styles.xml", False)] if styles else []
    word = "wordprocessingml."
    parts = [
        ("word/document.xml", word + "document.main+xml"),
        ("word/numbering.xml", word + "numbering+xml"),
    ]
    parts += [("word/styles.xml", word + "styles+xml")] if styles else []
    parts += [("word/footnotes.xml", word + "footnotes+xml")] if footnotes else []
    if footnotes:
        rels.append(("rIdNotes", "footnotes", "footnotes.xml", False))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("[Content_Types].xml", _content_types(parts))
        out.writestr("_rels/.rels", _rels([("rId1", "officeDocument", "word/document.xml", False)]))
        out.writestr(
            "word/document.xml",
            document
            or (HEAD + f"<w:document {W_NS}><w:body>{body}<w:sectPr/></w:body></w:document>"),
        )
        out.writestr("word/_rels/document.xml.rels", _rels(rels))
        if styles:
            out.writestr("word/styles.xml", styles)
        out.writestr("word/numbering.xml", NUMBERING)
        if footnotes:
            notes = "".join(
                f'<w:footnote w:id="{key}"><w:p>{r(text)}</w:p></w:footnote>'
                for key, text in footnotes.items()
            )
            out.writestr("word/footnotes.xml", HEAD + f"<w:footnotes {W_NS}>{notes}</w:footnotes>")
        for name, data in media.items():
            out.writestr("word/media/" + name, data)


# -- Excel -------------------------------------------------------------------


def cell(ref, value, style=None):
    """An Excel cell. Strings are written inline; ("s", n) is shared string n."""
    s = f' s="{style}"' if style is not None else ""
    if isinstance(value, tuple):
        kind, raw = value
        if kind == "f":  # a formula with its cached result
            return f'<c r="{ref}"{s}><f>{escape(raw[0])}</f><v>{raw[1]}</v></c>'
        return f'<c r="{ref}"{s} t="{kind}"><v>{escape(str(raw))}</v></c>'
    if isinstance(value, bool):
        return f'<c r="{ref}"{s} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{s}><v>{value!r}</v></c>'
    return f'<c r="{ref}"{s} t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def letters(index):
    text = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        text = chr(65 + rest) + text
    return text


def grid(rows, first_row=1, first_col=0, styles=None):
    """Sheet XML for a list of rows. styles: {column index: style} for every row after the first."""
    out = []
    for offset, row in enumerate(rows):
        number = first_row + offset
        cells = "".join(
            cell(
                f"{letters(first_col + index)}{number}",
                value,
                (styles or {}).get(index) if offset else None,
            )
            for index, value in enumerate(row)
            if value is not None
        )
        out.append(f'<row r="{number}">{cells}</row>')
    return "".join(out)


XLSX_STYLES = (
    HEAD
    + """<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd\\ hh:mm"/><numFmt numFmtId="165" formatCode="&quot;$&quot;#,##0.00"/></numFmts>
<cellXfs count="6"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/><xf numFmtId="10"/><xf numFmtId="165"/><xf numFmtId="21"/></cellXfs>
</styleSheet>"""
)
# Styles above: 1 date, 2 date and time, 3 percent, 4 currency, 5 time.


def write_xlsx(path, sheets, shared=(), active=0, date1904=False, styles=XLSX_STYLES):
    """sheets: (name, sheet data XML, state) tuples. shared: shared strings, plain or as XML."""
    kind = "spreadsheetml."
    numbers = range(1, len(sheets) + 1)
    parts = [
        ("xl/workbook.xml", kind + "sheet.main+xml"),
        ("xl/sharedStrings.xml", kind + "sharedStrings+xml"),
        *((f"xl/worksheets/sheet{n}.xml", kind + "worksheet+xml") for n in numbers),
    ]
    parts += [("xl/styles.xml", kind + "styles+xml")] if styles else []
    listed = "".join(
        f'<sheet name="{_attr(name)}" sheetId="{n}" r:id="rId{n}"'
        + (f' state="{state}"' if state else "")
        + "/>"
        for n, (name, _, state) in zip(numbers, sheets)
    )
    date_system = ' date1904="1"' if date1904 else ""
    workbook = (
        f"<workbook {S_NS}><workbookPr{date_system}/>"
        f'<bookViews><workbookView activeTab="{active}"/></bookViews>'
        f"<sheets>{listed}</sheets></workbook>"
    )
    # Excel writes relative targets; some tools write absolute ones. Test both.
    rels = [
        (
            f"rId{n}",
            "worksheet",
            f"/xl/worksheets/sheet{n}.xml" if n % 2 == 0 else f"worksheets/sheet{n}.xml",
            False,
        )
        for n in numbers
    ]
    rels += [
        ("rIdS", "sharedStrings", "sharedStrings.xml", False),
        ("rIdT", "styles", "styles.xml", False),
    ]
    items = "".join(
        f"<si>{item}</si>" if item.startswith("<") else f"<si><t>{escape(item)}</t></si>"
        for item in shared
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("[Content_Types].xml", _content_types(parts))
        out.writestr("_rels/.rels", _rels([("rId1", "officeDocument", "xl/workbook.xml", False)]))
        out.writestr("xl/workbook.xml", HEAD + workbook)
        out.writestr("xl/_rels/workbook.xml.rels", _rels(rels))
        for n, (_, data, _) in zip(numbers, sheets):
            out.writestr(
                f"xl/worksheets/sheet{n}.xml",
                f"{HEAD}<worksheet {S_NS}><sheetData>{data}</sheetData></worksheet>",
            )
        out.writestr(
            "xl/sharedStrings.xml", f'{HEAD}<sst {S_NS} count="{len(shared)}">{items}</sst>'
        )
        if styles:
            out.writestr("xl/styles.xml", styles)


# -- demo files --------------------------------------------------------------


def demo_docx(path):
    body = "".join(
        [
            p("Quarterly review", "Title"),
            p("Detection quality, October", "Subtitle"),
            p("Summary", "Heading1"),
            p(
                runs=r("Precision rose to ")
                + r("0.912", "b")
                + r(" on the indoor split, and ")
                + r("recall", "i")
                + r(" held steady.")
                + '<w:r><w:footnoteReference w:id="2"/></w:r>'
            ),
            p(
                runs=r("Run ")
                + r("eval.py --split indoor", font="Consolas")
                + r(" to reproduce it.")
            ),
            p("python eval.py \\", "SourceCode"),
            p("    --split indoor --threshold 0.45", "SourceCode"),
            p("Findings", "Heading1"),
            p("Fewer false alarms at night", num=("1", 0)),
            p("Mostly from the new crops", num=("1", 1)),
            p("Better recall on small objects", num=("1", 0)),
            p("Next steps", "Heading2"),
            p("Relabel the outdoor set", num=("2", 0)),
            p("Check the thresholds", num=("2", 0)),
            p("Night clips first", num=("2", 1)),
            p("Results", "Heading1"),
            table(
                [
                    ["Split", "Precision", "Recall"],
                    ["indoor", "0.912", "0.874"],
                    ["outdoor", "0.887", "0.851"],
                    [("Both splits use the October labels.", {"span": 3})],
                ]
            ),
            p(runs=image("rIdImg", descr="Precision by week")),
            p("Measure what matters, then measure it again.", "Quote"),
            p(
                runs=r("See the ")
                + '<w:hyperlink r:id="rIdLink">'
                + r("project page")
                + "</w:hyperlink>"
                + r(" or jump back to the ")
                + '<w:hyperlink w:anchor="summary">'
                + r("summary")
                + "</w:hyperlink>"
                + r(".")
            ),
            p("Appendix", "Heading1"),
            p(
                runs='<w:bookmarkStart w:id="0" w:name="summary"/><w:bookmarkEnd w:id="0"/>'
                + r("Thresholds were tuned on the validation split.")
            ),
            p(runs=r("<script>window.__pwned = 1</script> stays text.")),
        ]
    )
    write_docx(
        path,
        body,
        rels=[
            ("rIdImg", "image", "media/chart.png", False),
            ("rIdLink", "hyperlink", "https://example.com/project", True),
        ],
        media={"chart.png": png(200, 100, (60, 110, 200))},
        footnotes={"2": "Measured on 4,210 clips."},
    )


def demo_xlsx(path):
    results = [["split", "precision", "recall", "clips", "updated", "share"]]
    for index in range(1, 61):
        results.append(
            [
                f"split-{index:02d}",
                round(0.8 + (index % 17) / 100, 3),
                round(0.75 + (index % 13) / 100, 3),
                100 + index * 7,
                45200 + index,
                (index % 9) / 10,
            ]
        )
    budget = [
        ["Item", "Cost", "Approved"],
        ["GPUs", 12000.5, True],
        ["Storage", 800, False],
        ["Total", ("f", ("SUM(B2:B3)", 12800.5)), None],
    ]
    write_xlsx(
        path,
        [
            ("Results", grid(results, styles={4: 1, 5: 3}), None),
            ("Budget", grid(budget, first_row=2, first_col=1, styles={1: 4}), None),
            ("Scratch", grid([["hidden sheet"]]), "hidden"),
        ],
    )
