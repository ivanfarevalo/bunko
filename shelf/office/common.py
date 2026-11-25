"""Reading the zip and XML inside Office files, treating them as untrusted.

XML with a DOCTYPE is refused (Office never writes one, and that's where entity
bombs live), and every part is read with a size cap, however large the zip
claims it is.
"""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
import zipfile

PART_MAX = 64 * 1024 * 1024  # most XML read from one part of a document
REL_NAMESPACES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/officeDocument/relationships",  # "Strict" files
)


class OfficeError(ValueError):
    """A file that can't be shown, with a message for the user."""


def plain_name(key: str) -> str:
    """Drop the namespace, keeping r: on relationship attributes (r:id, r:embed)."""
    if key[:1] != "{":
        return key
    namespace, _, local = key[1:].partition("}")
    return "r:" + local if namespace in REL_NAMESPACES else local


def refuse_doctype(*_):
    raise OfficeError("This file contains XML that Office doesn't write (a DOCTYPE).")


class PlainTree(ET.TreeBuilder):
    """Builds elements with plain names, so <w:p> is just "p"."""

    def start(self, tag, attrs):
        return super().start(
            plain_name(tag), {plain_name(key): value for key, value in attrs.items()}
        )

    def end(self, tag):
        return super().end(plain_name(tag))

    doctype = staticmethod(refuse_doctype)


class CappedReader:
    """A file-like reader that fails once more than `cap` bytes have been read."""

    def __init__(self, handle, cap: int, part: str):
        self.handle, self.left, self.part = handle, cap, part

    def read(self, size: int) -> bytes:
        chunk = self.handle.read(min(size, self.left + 1))
        self.left -= len(chunk)
        if self.left < 0:
            raise OfficeError(f"Part of this file ({self.part}) is too large to show.")
        return chunk


def feed(archive: zipfile.ZipFile, part: str, target, cap: int):
    parser = ET.XMLParser(target=target)
    with archive.open(part) as handle:
        source = CappedReader(handle, cap, part)
        while True:
            chunk = source.read(1 << 20)
            if not chunk:
                break
            parser.feed(chunk)
    return parser.close()


def parse_part(archive: zipfile.ZipFile, part: str):
    """The part as an element tree, or None if the file doesn't have it."""
    if part not in archive.NameToInfo:
        return None
    return feed(archive, part, PlainTree(), PART_MAX)


def open_package(real: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(real)
    except (zipfile.BadZipFile, OSError):
        raise OfficeError(
            "This isn't a valid Office file. It may be damaged, password-protected, "
            "or an older format saved with a newer extension."
        ) from None


def relationships(archive: zipfile.ZipFile, part: str) -> dict:
    """A part's relationships: id -> (target, external)."""
    folder, name = posixpath.split(part)
    tree = parse_part(archive, posixpath.join(folder, "_rels", name + ".rels"))
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


def toggled(element) -> bool:
    """A Word toggle such as <w:b/>, which w:val="0" or "false" turns off."""
    return element is not None and element.get("val", "true").lower() not in (
        "0",
        "false",
        "off",
        "none",
    )


def find_child(element, name):
    return element.find(name) if element is not None else None


def child_val(element, name, default=None):
    found = find_child(element, name)
    return found.get("val", default) if found is not None else default


def letters(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA: Excel's column names, and Word's lettered lists."""
    text = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        text = chr(65 + rest) + text
    return text
