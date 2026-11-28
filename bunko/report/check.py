"""Mechanical checks on a report, so an agent can fix what it would otherwise miss.

Errors make `bunko report check` fail; warnings are worth a look. `fix` rebuilds
the contents list from the page's sections, which is the most common slip.
"""

from __future__ import annotations

import os
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from .themes import Theme, fill

CONTENTS = re.compile(r"(<!-- bunko:contents -->\n?)(.*?)(\n?<!-- /bunko:contents -->)", re.S)
NETWORK_OK = ("fonts.googleapis.com", "fonts.gstatic.com")
WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.doctype = False
        self.charset = False
        self.kind = False
        self.ids = {}  # id -> line
        self.sections = []  # (id, line, heading)
        self.contents = []  # (target, line)
        self.anchors = []  # (target, line)
        self.resources = []  # (tag, attribute, value, line)
        self._nav_depth = 0
        self._section = None
        self._heading = None

    def handle_decl(self, decl):
        if decl.lower().startswith("doctype"):
            self.doctype = True

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        line = self.getpos()[0]
        if attrs.get("id"):
            self.ids.setdefault(attrs["id"], line)
        if tag == "meta":
            if "charset" in attrs:
                self.charset = True
            if attrs.get("name") == "bunko:kind":
                self.kind = True
        if tag == "nav" and "toc" in (attrs.get("class") or "").split():
            self._nav_depth = 1
        elif tag == "nav" and self._nav_depth:
            self._nav_depth += 1
        if tag == "section" and attrs.get("id"):
            self._section = [attrs["id"], line, ""]
            self.sections.append(self._section)
        if tag == "h2" and self._section is not None and not self._section[2]:
            self._heading = []
        href = attrs.get("href")
        if tag == "a" and href and href.startswith("#") and len(href) > 1:
            (self.contents if self._nav_depth else self.anchors).append((unquote(href[1:]), line))
        for attribute in ("src", "href", "poster", "data"):
            value = attrs.get(attribute)
            if value and not (tag == "a" and value.startswith("#")):
                self.resources.append((tag, attribute, value, line))

    def handle_endtag(self, tag):
        if tag == "nav" and self._nav_depth:
            self._nav_depth -= 1
        if tag == "h2" and self._heading is not None:
            self._section[2] = "".join(self._heading).strip()
            self._heading = None

    def handle_data(self, data):
        if self._heading is not None:
            self._heading.append(data)


def check(path: str) -> list:
    """Problems as dicts: level ("error" or "warning"), line, message."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    page = _Page()
    page.feed(text)
    problems = []

    def add(level, line, message):
        problems.append({"level": level, "line": line, "message": message})

    if not page.doctype:
        add("error", 1, "No <!doctype html>: browsers render the page in quirks mode.")
    if not page.charset:
        add("error", 1, 'No <meta charset="utf-8">: text may garble when opened from disk.')
    if not page.kind:
        add("warning", 1, 'No <meta name="bunko:kind">: Bunko won\'t list this as a report.')
    listed = {target for target, _ in page.contents}
    for section_id, line, heading in page.sections:
        if section_id not in listed:
            add(
                "error",
                line,
                f'Section "{heading or section_id}" (#{section_id}) is missing from the contents.',
            )
    for target, line in page.contents + page.anchors:
        if target not in page.ids:
            add("error", line, f"Link to #{target}, but nothing on the page has that id.")
    folder = os.path.dirname(os.path.abspath(path))
    for tag, attribute, value, line in page.resources:
        problems.extend(_resource(folder, tag, attribute, value, line))
    return sorted(problems, key=lambda problem: problem["line"])


def _resource(folder: str, tag: str, attribute: str, value: str, line: int) -> list:
    if value.startswith(("data:", "mailto:", "javascript:", "#", "about:", "blob:")):
        return []
    url = urlsplit(value)
    if url.scheme in ("http", "https") or value.startswith("//"):
        if (
            tag in ("script", "link", "img", "video", "audio", "source", "iframe")
            and url.hostname not in NETWORK_OK
        ):
            return [
                _problem(
                    "warning",
                    line,
                    f"<{tag}> loads {value} from the network: it won't show offline.",
                )
            ]
        return []
    if url.scheme == "file" or value.startswith("/") or WINDOWS_PATH.match(value):
        return [
            _problem(
                "warning",
                line,
                f"Absolute path {value}: it only works on this machine. Use a path relative to the report.",
            )
        ]
    if url.scheme:
        return []
    target = os.path.normpath(os.path.join(folder, unquote(url.path)))
    if url.path and not os.path.exists(target):
        return [
            _problem(
                "error",
                line,
                f"{attribute}={value!r} points at a file that doesn't exist ({target}).",
            )
        ]
    return []


def _problem(level: str, line: int, message: str) -> dict:
    return {"level": level, "line": line, "message": message}


def fix(path: str, theme: Theme) -> bool:
    """Rebuild the contents list from the sections. False if the page has no contents markers."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    match = CONTENTS.search(text)
    if not match:
        return False
    page = _Page()
    page.feed(text)
    item = theme.file("contents-item.html").strip()
    entries = []
    for number, (section_id, _, heading) in enumerate(page.sections):
        values = {
            "id": escape(section_id),
            "number": f"{number:02d}",
            "title": escape(heading or section_id),
        }
        entries.append(fill(item, values))
    rebuilt = text[: match.start(2)] + "\n".join(entries) + text[match.end(2) :]
    if rebuilt != text:
        with open(path, "w", encoding="utf-8") as out:
            out.write(rebuilt)
    return True
