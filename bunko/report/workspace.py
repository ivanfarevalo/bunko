"""Workspaces and the reports in them: where a report goes, and what's already there."""

from __future__ import annotations

import datetime
import os
import re
import subprocess
from html import unescape

from .. import registry
from .config import ConfigError, Settings
from .themes import Theme, slugify

META = re.compile(r'<meta\s+name="bunko:(\w+)"\s+content="([^"]*)"', re.I)
TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
HEAD_BYTES = 16 * 1024
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "runs", "data"}


def today() -> datetime.date:
    return datetime.date.today()


def folder_name(pattern: str, name: str) -> str:
    try:
        return pattern.format(slug=slugify(name), date=today().strftime("%Y%m%d"), name=name)
    except (KeyError, IndexError, ValueError) as error:
        raise ConfigError(
            f"Bad folder pattern {pattern!r}: use {{slug}}, {{date}}, and {{name}}"
        ) from error


def current(settings: Settings, cwd: str | None = None) -> str | None:
    """The workspace the working folder is in: the top-level folder under the root."""
    here = os.path.realpath(cwd or os.getcwd())
    root = os.path.realpath(settings.root)
    if here == root or os.path.commonpath([root, here]) != root:
        return None
    return os.path.join(root, os.path.relpath(here, root).split(os.sep)[0])


def resolve(settings: Settings, workspace: str | None, cwd: str | None = None):
    """(path, exists) for a workspace given as a path, a name, or the current folder."""
    if workspace is None:
        path = current(settings, cwd)
        return (path, True) if path else (None, False)
    expanded = os.path.expanduser(workspace)
    if os.sep in workspace or os.path.isdir(expanded):
        path = os.path.abspath(expanded)
        return path, os.path.isdir(path)
    existing = match(settings, workspace)
    if existing:
        return existing, True
    path = os.path.join(settings.root, folder_name(settings.layout()["folder"], workspace))
    return path, os.path.isdir(path)


def match(settings: Settings, name: str) -> str | None:
    """An existing workspace under the root whose folder name is, or ends with, the name's slug."""
    slug = slugify(name)
    try:
        entries = sorted(os.listdir(settings.root), reverse=True)  # newest dated folder first
    except OSError:
        return None
    for entry in entries:
        if entry in (slug, name) or entry.endswith("_" + slug):
            path = os.path.join(settings.root, entry)
            if os.path.isdir(path):
                return path
    return None


def create(settings: Settings, path: str) -> None:
    os.makedirs(path, exist_ok=True)
    for sub in settings.layout().get("subdirs", []):
        os.makedirs(os.path.join(path, sub), exist_ok=True)


def report_path(settings: Settings, workspace: str, kind: str, title: str) -> str:
    pattern = settings.kind(kind).get("file", "{slug}.html")
    name = pattern.format(slug=slugify(title), date=today().strftime("%Y%m%d"), kind=kind)
    return os.path.join(workspace, settings.place(kind), name)


def builder_path(workspace: str, report: str) -> str:
    folder = os.path.join(workspace, "report")
    if not os.path.isdir(folder):
        folder = os.path.dirname(report)
    stem = os.path.splitext(os.path.basename(report))[0]
    return os.path.join(folder, f"build_{stem.replace('-', '_')}.py")


def git_commit(folder: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", folder, "log", "-1", "--format=%h %s"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not done.stdout.strip():
        return None
    dirty = subprocess.run(
        ["git", "-C", folder, "status", "--porcelain"], capture_output=True, text=True, timeout=5
    ).stdout.strip()
    return done.stdout.strip() + (" (with uncommitted changes)" if dirty else "")


def link(path: str) -> str | None:
    found = registry.server_for(path, registry.running())
    if not found:
        return None
    record, rel = found
    if registry.is_hidden(rel) and not record.get("hidden"):
        return None
    return registry.app_url(record["url"], rel)


def new(
    settings: Settings, kind: str, title: str, workspace: str | None = None, cwd: str | None = None
) -> dict:
    """Find or create the workspace and the report file. Never overwrites a report."""
    definition = settings.kind(kind)
    path, exists = resolve(settings, workspace, cwd)
    if path is None:
        raise ConfigError(
            "Not inside a workspace. Pass --workspace with a name (a new folder under "
            f"{settings.root}) or a path."
        )
    if not exists:
        create(settings, path)
    report = report_path(settings, path, kind, title)
    result = {
        "workspace": path,
        "workspace_created": not exists,
        "report": report,
        "existed": os.path.exists(report),
        "kind": kind,
        "guidance": definition.get("guidance", ""),
        "theme": definition.get("theme") or settings.data["theme"],
        "builder": None,
    }
    if definition.get("builder"):
        result["builder"] = builder_path(path, report)
    if not result["existed"]:
        os.makedirs(os.path.dirname(report), exist_ok=True)
        page = Theme(result["theme"], settings).render(
            scaffold(settings, kind, title, path, report, result["builder"])
        )
        with open(report, "w", encoding="utf-8") as out:
            out.write(page)
        if result["builder"] and not os.path.exists(result["builder"]):
            write_builder(result["builder"], report, title, kind, path)
    result["link"] = link(report)
    return result


def scaffold(
    settings: Settings, kind: str, title: str, workspace: str, report: str, builder: str | None
) -> dict:
    definition = settings.kind(kind)
    created = today().isoformat()
    name = os.path.basename(workspace)
    return {
        "title": title,
        "kicker": f"{name} · {kind}",
        "summary": "One-paragraph summary.",
        "sections": [
            {"title": section, "body": '<p class="muted">To write.</p>'}
            for section in definition.get("sections", ["Summary"])
        ],
        "meta": {"kind": kind, "workspace": name, "created": created, "updated": created},
        "provenance": provenance(workspace, report, builder, created),
    }


def provenance(workspace: str, report: str, builder: str | None, created: str) -> dict:
    facts = {"Created": created, "Workspace": workspace}
    if builder:
        facts["Rebuild with"] = f"python3 {os.path.relpath(builder, workspace)}  (in {workspace})"
    commit = git_commit(workspace)
    if commit:
        facts["Code at"] = commit
    return facts


BUILDER = '''#!/usr/bin/env python3
"""Build {report_name} from the results in this workspace. Rerun it whenever the results change."""

import json
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE = pathlib.Path({workspace!r})
REPORT = pathlib.Path({report!r})


def sections():
    """Each section: a title and its HTML. Read results from WORKSPACE and turn them into tables and figures."""
    return [
        {{"title": "Summary", "body": "<p>To write.</p>"}},
    ]


spec = {{
    "title": {title!r},
    "kicker": {kicker!r},
    "summary": "One-paragraph summary.",
    "sections": sections(),
    "meta": {{"kind": {kind!r}, "workspace": WORKSPACE.name}},
    "provenance": {{"Rebuild with": "python3 " + str(pathlib.Path(__file__).relative_to(WORKSPACE))}},
}}
subprocess.run(["bunko", "report", "render", "-o", str(REPORT)], input=json.dumps(spec), text=True, check=True)
print(REPORT)
'''


def write_builder(path: str, report: str, title: str, kind: str, workspace: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as out:
        out.write(
            BUILDER.format(
                report_name=os.path.basename(report),
                workspace=workspace,
                report=report,
                title=title,
                kicker=f"{os.path.basename(workspace)} · {kind}",
                kind=kind,
            )
        )
    os.chmod(path, 0o755)


def reports(settings: Settings, workspace: str) -> list:
    """The Bunko reports in a workspace (pages carrying bunko: meta tags), newest first."""
    found = []
    for folder, dirs, files in os.walk(workspace):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not name.startswith(".")]
        for name in files:
            if not name.endswith((".html", ".htm")):
                continue
            path = os.path.join(folder, name)
            info = read_meta(path)
            if info:
                found.append(info)
    found.sort(key=lambda item: item.get("updated") or item.get("created") or "", reverse=True)
    return found


def read_meta(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            head = handle.read(HEAD_BYTES)
    except OSError:
        return None
    meta = {key.lower(): unescape(value) for key, value in META.findall(head)}
    if "kind" not in meta:
        return None
    title = TITLE.search(head)
    return {"path": path, "title": unescape(title.group(1).strip()) if title else "", **meta}
