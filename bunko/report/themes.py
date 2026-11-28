"""Report themes, and rendering a page from a theme.

A theme is a folder of plain files: template.html (the page), section.html,
contents-item.html and provenance.html (snippets), style.css, and an optional
script.js. Placeholders are written {{name}}. A theme may leave a file out to
use the house theme's.

Themes are found by name in the project's .bunko/themes/, then
~/.config/bunko/themes/, then the themes built into Bunko. A path works too.
"""

from __future__ import annotations

import os
import pkgutil
import re
import shutil
from html import escape

from ..storage import config_dir
from .config import ConfigError, Settings

BUILT_IN = ("house",)
FILES = (
    "template.html",
    "section.html",
    "contents-item.html",
    "provenance.html",
    "style.css",
    "script.js",
)
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def _built_in(name: str, filename: str) -> str | None:
    try:
        data = pkgutil.get_data("bunko.report", f"themes/{name}/{filename}")
    except (OSError, KeyError):
        return None
    return data.decode("utf-8") if data is not None else None


def search_dirs(settings: Settings) -> list:
    dirs = []
    if settings.project_file:
        dirs.append(os.path.join(os.path.dirname(settings.project_file), "themes"))
    dirs.append(os.path.join(config_dir(), "themes"))
    return dirs


def locate(name: str, settings: Settings) -> str | None:
    """The folder of a user or project theme, or None for a built-in one."""
    if os.sep in name or name.startswith("."):
        path = os.path.abspath(os.path.expanduser(name))
        if os.path.isdir(path):
            return path
        raise ConfigError(f"No theme folder at {path}")
    for folder in search_dirs(settings):
        path = os.path.join(folder, name)
        if os.path.isdir(path):
            return path
    if name in BUILT_IN:
        return None
    raise ConfigError(f"No theme named {name!r}. Known themes: {', '.join(available(settings))}")


def available(settings: Settings) -> list:
    names = set(BUILT_IN)
    for folder in search_dirs(settings):
        if os.path.isdir(folder):
            names.update(
                entry for entry in os.listdir(folder) if os.path.isdir(os.path.join(folder, entry))
            )
    return sorted(names)


class Theme:
    def __init__(self, name: str, settings: Settings):
        self.name = name
        self.folder = locate(name, settings)

    def file(self, filename: str) -> str:
        if self.folder:
            path = os.path.join(self.folder, filename)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    return handle.read()
        builtin = _built_in("house" if self.folder else self.name, filename)
        return builtin if builtin is not None else ""

    def render(self, spec: dict) -> str:
        """A complete page from a spec: title, kicker, summary, sections, meta, provenance."""
        sections = spec.get("sections", [])
        used = set()
        contents, bodies = [], []
        for number, section in enumerate(sections):
            section_id = section.get("id") or unique(slugify(section["title"]), used)
            used.add(section_id)
            values = {
                "id": escape(section_id),
                "number": f"{number:02d}",
                "label": escape(section.get("label") or f"Part {number:02d}"),
                "title": escape(section["title"]),
                "body": section.get("body", ""),
            }
            contents.append(fill(self.file("contents-item.html"), values).strip())
            bodies.append(fill(self.file("section.html"), values).strip())
        page = {
            "title": escape(spec["title"]),
            "kicker": escape(spec.get("kicker", "")),
            "summary": spec.get("summary", ""),
            "meta": meta_tags(spec.get("meta", {})),
            "script": self.file("script.js").strip(),
            "style": self.file("style.css").strip(),
            "contents": "\n".join(contents),
            "sections": "\n".join(bodies),
            "provenance": self.provenance(spec.get("provenance", {})),
        }
        return fill(self.file("template.html"), page)

    def provenance(self, facts: dict) -> str:
        if not facts:
            return ""
        rows = []
        for label, value in facts.items():
            if value in (None, "", []):
                continue
            if isinstance(value, (list, tuple)):
                value = "<br>".join(f"<code>{escape(str(item))}</code>" for item in value)
            else:
                value = escape(str(value))
            rows.append(f"<dt>{escape(label)}</dt><dd>{value}</dd>")
        return fill(self.file("provenance.html"), {"rows": "\n".join(rows)}).strip()


def fill(template: str, values: dict) -> str:
    return PLACEHOLDER.sub(lambda match: str(values.get(match.group(1), "")), template)


def meta_tags(meta: dict) -> str:
    return "\n".join(
        f'<meta name="bunko:{escape(key)}" content="{escape(str(value))}">'
        for key, value in meta.items()
        if value not in (None, "")
    )


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-_")
    return slug or "section"


def unique(slug: str, used: set) -> str:
    candidate, number = slug, 2
    while candidate in used:
        candidate = f"{slug}-{number}"
        number += 1
    return candidate


def copy_theme(source: str, name: str, settings: Settings, project: bool = False) -> str:
    """Start a new theme as a copy of an existing one, and return its folder."""
    if project:
        bunko_dir = (
            os.path.dirname(settings.project_file)
            if settings.project_file
            else os.path.join(os.getcwd(), ".bunko")
        )
        base = os.path.join(bunko_dir, "themes")
    else:
        base = os.path.join(config_dir(), "themes")
    target = os.path.join(base, name)
    if os.path.exists(target):
        raise ConfigError(f"A theme named {name!r} already exists at {target}")
    origin = Theme(source, settings)
    if origin.folder:
        shutil.copytree(origin.folder, target)  # also copies any extra assets
    else:
        os.makedirs(target)
    for filename in FILES:
        path = os.path.join(target, filename)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as out:
                out.write(origin.file(filename))
    return target
