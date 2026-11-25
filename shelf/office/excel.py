"""Excel workbooks (.xlsx) as rows of text for the table viewer.

Each cell becomes the text Excel would show for its value: formulas show their
last calculated result, and dates, times, and percentages are formatted.
Other number formats are left out, so numbers sort as numbers.
"""

from __future__ import annotations

import contextlib
import datetime
import re
import zipfile

from .common import (
    OfficeError,
    feed,
    letters,
    open_package,
    parse_part,
    plain_name,
    refuse_doctype,
    relationships,
)

SHEET_XML_MAX = 512 * 1024 * 1024  # a worksheet is streamed, so it may be larger
SHEET_ROWS = 100_000  # rows sent to the browser per sheet
SHEET_COLUMNS = 1_000
DATE_FORMATS = set(range(14, 18)) | {22, 27, 30, 36, 50, 57}
TIME_FORMATS = {18, 19, 20, 21, 45, 46, 47}
PERCENT_FORMATS = {9, 10}
CELL_REF = re.compile(r"([A-Za-z]{1,3})(\d+)")


def _column_index(name: str) -> int:
    index = 0
    for char in name.upper():
        index = index * 26 + ord(char) - 64
    return index - 1


def _format_kind(code: str):
    """ "date", "time", "datetime", "percent", or None for an Excel number format."""
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
        tag = plain_name(tag)
        if tag == "si":
            self.text = []
        elif tag == "rPh":
            self.depth_skip += 1
        elif tag == "t" and not self.depth_skip:
            self.inside_t = True

    def end(self, tag):
        tag = plain_name(tag)
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

    doctype = staticmethod(refuse_doctype)


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
        tag = plain_name(tag)
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
        tag = plain_name(tag)
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

    doctype = staticmethod(refuse_doctype)


class _Book:
    def __init__(self, archive: zipfile.ZipFile):
        self.archive = archive
        workbook = parse_part(archive, "xl/workbook.xml")
        if workbook is None:
            raise OfficeError("This file has no workbook in it.")
        rels = relationships(archive, "xl/workbook.xml")
        self.sheets = []
        for sheet in workbook.iter("sheet"):
            target = rels.get(sheet.get("r:id"))
            if target and not target[1]:
                self.sheets.append(
                    {
                        "name": sheet.get("name", "Sheet"),
                        "part": target[0],
                        "hidden": sheet.get("state", "visible") != "visible",
                    }
                )
        view = next(workbook.iter("workbookView"), None)
        active = view.get("activeTab", "0") if view is not None else "0"
        self.active = int(active) if active.isdigit() and int(active) < len(self.sheets) else 0
        pr = next(workbook.iter("workbookPr"), None)
        flag = (pr.get("date1904", "0") if pr is not None else "0").lower()
        self.epoch = (
            datetime.datetime(1904, 1, 1)
            if flag in ("1", "true")
            else datetime.datetime(1899, 12, 30)
        )
        self.strings = []
        if "xl/sharedStrings.xml" in archive.NameToInfo:
            self.strings = feed(archive, "xl/sharedStrings.xml", _Strings(), SHEET_XML_MAX)
        self.formats = self._formats()

    def _formats(self) -> list:
        """The kind of value each cell style shows, indexed by the cell's s attribute."""
        tree = parse_part(self.archive, "xl/styles.xml")
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
        shown = (
            self.formats[int(style)]
            if style and style.isdigit() and int(style) < len(self.formats)
            else None
        )
        if shown in ("date", "datetime", "time") and -1 < number < 2958466:
            moment = self.epoch + datetime.timedelta(days=number)
            moment = moment.replace(microsecond=0) + datetime.timedelta(
                seconds=round(moment.microsecond / 1e6)
            )
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
            with contextlib.suppress(_Stop):  # the row cap was reached
                feed(self.archive, info["part"], reader, SHEET_XML_MAX)
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
        return {
            "rows": rows,
            "first_row": first_row,
            "first_col": first_col,
            "truncated": reader.truncated,
            "wide": reader.wide,
        }


def _number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.15g}"


def xlsx_sheet(real: str, sheet=None) -> dict:
    with open_package(real) as archive:
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
                raise OfficeError(f"This workbook has no sheet {sheet}.")
        out = book.sheet(index)
    out["sheets"] = [{"name": item["name"], "hidden": item["hidden"]} for item in book.sheets]
    out["sheet"] = index
    out["first_letter"] = letters(out["first_col"])
    return out
