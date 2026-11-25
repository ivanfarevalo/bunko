"""Word and Excel files, converted with the standard library for the viewer."""

from __future__ import annotations

import threading
import xml.etree.ElementTree as ET
import zipfile

from .common import OfficeError
from .excel import xlsx_sheet
from .word import docx_image, docx_page

__all__ = ["Office", "OfficeError", "docx_image", "docx_page", "kind_of", "xlsx_sheet"]

WORD_EXTS = {"docx", "docm", "dotx", "dotm"}
EXCEL_EXTS = {"xlsx", "xlsm", "xltx", "xltm"}


def kind_of(path: str) -> str | None:
    """ "docx", "xlsx", or None, from the file's extension."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return "docx" if ext in WORD_EXTS else "xlsx" if ext in EXCEL_EXTS else None


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
        if issubclass(
            kind,
            (
                zipfile.BadZipFile,
                zipfile.LargeZipFile,
                KeyError,
                EOFError,
                OSError,
                RuntimeError,
                NotImplementedError,
                ValueError,
                IndexError,
            ),
        ):
            raise OfficeError(
                "This file couldn't be read. It may be damaged or encrypted."
            ) from error
        return False
