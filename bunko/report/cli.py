"""`bunko report ...`: settings, themes, and report files, for people and agents.

Every command prints JSON, so an agent can read the result, and a person can too.
Settings changes go to the user's file, or to the project's with --project.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import check as checker
from . import config, themes, workspace
from .config import ConfigError, Settings


def emit(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def split(text: str | None) -> list:
    return [item.strip() for item in (text or "").split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bunko report",
        description="Make and check HTML reports in a consistent style and layout. See docs/reports.md.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def scoped(name, **kw):
        command = sub.add_parser(name, **kw)
        command.add_argument(
            "--project",
            action="store_true",
            help="change the project's settings (.bunko/report.json)",
        )
        return command

    init = scoped("init", help="first-time setup: where workspaces go, the layout, and the theme")
    init.add_argument("--root", help="folder that holds the workspaces (default ~/reports)")
    init.add_argument("--layout", help="layout for new workspaces (default simple)")
    init.add_argument("--theme", help="theme for reports (default house)")

    settings = scoped("config", help="show or change settings")
    settings.add_argument("action", choices=["show", "set"])
    settings.add_argument("key", nargs="?", choices=config.SCALARS)
    settings.add_argument("value", nargs="?")

    kind = scoped("kind", help="list, add, edit, or remove report kinds")
    kind.add_argument("action", choices=["list", "add", "edit", "remove"])
    kind.add_argument("name", nargs="?")
    kind.add_argument("--description", help="one line; the agent picks kinds by it")
    kind.add_argument(
        "--guidance", help="free text for the agent: tone, length, interactivity, ..."
    )
    kind.add_argument("--sections", help="starting outline, comma-separated")
    kind.add_argument(
        "--file", help="file name pattern, with {slug}, {date}, {kind} (default {slug}.html)"
    )
    kind.add_argument("--place", help="folder inside the workspace (default: the layout decides)")
    kind.add_argument(
        "--builder",
        dest="builder",
        action="store_const",
        const=True,
        default=None,
        help="give reports of this kind a builder script, so they can be rebuilt from data",
    )
    kind.add_argument("--no-builder", dest="builder", action="store_const", const=False)
    kind.add_argument("--theme", help="theme for this kind only")

    layout = scoped("layout", help="list, add, edit, remove, or choose workspace layouts")
    layout.add_argument("action", choices=["list", "add", "edit", "remove", "use"])
    layout.add_argument("name", nargs="?")
    layout.add_argument("--description")
    layout.add_argument(
        "--folder", help="workspace folder name pattern, with {slug}, {date}, {name}"
    )
    layout.add_argument("--subdirs", help="folders every new workspace gets, comma-separated")
    layout.add_argument(
        "--place",
        action="append",
        metavar="KIND=DIR",
        help="where reports of a kind go inside the workspace (* for the rest); repeatable",
    )

    theme = scoped("theme", help="list, copy, or choose themes")
    theme.add_argument("action", choices=["list", "new", "use"])
    theme.add_argument("name", nargs="?")
    theme.add_argument(
        "--from", dest="origin", default="house", help="theme to copy (default house)"
    )

    new = sub.add_parser(
        "new", help="find or create the workspace and the report file, and print their paths"
    )
    new.add_argument("kind")
    new.add_argument("title")
    new.add_argument(
        "--workspace",
        help="workspace name (a folder under the root) or path; default: the one you're in",
    )

    listing = sub.add_parser("list", help="the reports in a workspace")
    listing.add_argument("workspace", nargs="?", help="name or path; default: the one you're in")

    render = sub.add_parser("render", help="render a page from a JSON spec (for builder scripts)")
    render.add_argument("spec", nargs="?", default="-", help="spec file, or - for standard input")
    render.add_argument("-o", "--output", required=True)
    render.add_argument("--theme")

    checks = sub.add_parser("check", help="check a report for broken contents, links, and paths")
    checks.add_argument("file")
    checks.add_argument(
        "--fix", action="store_true", help="rebuild the contents list from the sections first"
    )
    return parser


def main(argv: list) -> None:
    args = build_parser().parse_args(argv)
    try:
        COMMANDS[args.command](args)
    except ConfigError as error:
        sys.exit(f"bunko report: {error}")


def cmd_init(args) -> None:
    values = {key: getattr(args, key) for key in config.SCALARS if getattr(args, key) is not None}
    _validate(values)

    def change(data):
        data.update(values)
        if not args.project:  # write the defaults out, so the user's file shows every setting
            for key in config.SCALARS:
                data.setdefault(key, config.DEFAULTS[key])

    path = config.update(change, args.project)
    os.makedirs(Settings().root, exist_ok=True)
    emit({"saved": path, "settings": _summary(Settings())})


def _validate(values: dict) -> None:
    settings = Settings()
    if values.get("layout"):
        settings.layout(values["layout"])
    if values.get("theme"):
        themes.locate(values["theme"], settings)


def cmd_config(args) -> None:
    if args.action == "show":
        settings = Settings()
        emit(
            {
                "files": {"user": settings.user_file, "project": settings.project_file},
                "configured": settings.configured,
                "root": settings.root,
                "settings": settings.data,
            }
        )
        return
    if not args.key or args.value is None:
        raise ConfigError("config set needs a key (root, layout, or theme) and a value")
    _validate({args.key: args.value})
    path = config.update(lambda data: data.__setitem__(args.key, args.value), args.project)
    emit({"saved": path, args.key: args.value})


def cmd_kind(args) -> None:
    settings = Settings()
    if args.action == "list":
        emit(settings.data["kinds"])
        return
    if not args.name:
        raise ConfigError(f"kind {args.action} needs a name")
    if args.action == "remove":
        settings.kind(args.name)
        path = config.update(
            lambda data: data.setdefault("kinds", {}).__setitem__(args.name, None), args.project
        )
        emit({"saved": path, "removed": args.name})
        return
    if args.action == "add" and args.name in settings.data["kinds"]:
        raise ConfigError(f"A kind named {args.name!r} exists; use kind edit")
    if args.action == "add" and not args.description:
        raise ConfigError("kind add needs --description")
    entry = dict(settings.kind(args.name)) if args.action == "edit" else {}
    for field in ("description", "guidance", "file", "place", "theme"):
        value = getattr(args, field)
        if value is not None:
            entry[field] = value
    if args.sections is not None:
        entry["sections"] = split(args.sections)
    if args.builder is not None:
        entry["builder"] = bool(args.builder)
    entry.setdefault("sections", ["Summary"])
    entry.setdefault("builder", False)
    if entry.get("theme"):
        themes.locate(entry["theme"], settings)
    path = config.update(
        lambda data: data.setdefault("kinds", {}).__setitem__(args.name, entry), args.project
    )
    emit({"saved": path, "kind": {args.name: entry}})


def cmd_layout(args) -> None:
    settings = Settings()
    if args.action == "list":
        emit({"current": settings.data["layout"], "layouts": settings.data["layouts"]})
        return
    if not args.name:
        raise ConfigError(f"layout {args.action} needs a name")
    if args.action == "use":
        settings.layout(args.name)
        path = config.update(lambda data: data.__setitem__("layout", args.name), args.project)
        emit({"saved": path, "layout": args.name})
        return
    if args.action == "remove":
        settings.layout(args.name)
        if settings.data["layout"] == args.name:
            raise ConfigError(
                f"{args.name!r} is the layout in use; choose another with layout use first"
            )
        path = config.update(
            lambda data: data.setdefault("layouts", {}).__setitem__(args.name, None), args.project
        )
        emit({"saved": path, "removed": args.name})
        return
    if args.action == "add" and args.name in settings.data["layouts"]:
        raise ConfigError(f"A layout named {args.name!r} exists; use layout edit")
    if args.action == "add" and not args.folder:
        raise ConfigError("layout add needs --folder, for example {date}_{slug}")
    entry = (
        dict(settings.layout(args.name)) if args.action == "edit" else {"subdirs": [], "places": {}}
    )
    if args.description is not None:
        entry["description"] = args.description
    if args.folder is not None:
        workspace.folder_name(args.folder, "check")
        entry["folder"] = args.folder
    if args.subdirs is not None:
        entry["subdirs"] = split(args.subdirs)
    for item in args.place or []:
        kind, sep, folder = item.partition("=")
        if not sep:
            raise ConfigError(f"--place takes KIND=DIR, not {item!r}")
        entry.setdefault("places", {})[kind.strip()] = folder.strip().strip("/")
    path = config.update(
        lambda data: data.setdefault("layouts", {}).__setitem__(args.name, entry), args.project
    )
    emit({"saved": path, "layout": {args.name: entry}})


def cmd_theme(args) -> None:
    settings = Settings()
    if args.action == "list":
        emit({"current": settings.data["theme"], "themes": themes.available(settings)})
        return
    if not args.name:
        raise ConfigError(f"theme {args.action} needs a name")
    if args.action == "new":
        folder = themes.copy_theme(args.origin, args.name, settings, args.project)
        emit({"created": folder, "files": sorted(os.listdir(folder))})
        return
    themes.locate(args.name, settings)
    path = config.update(lambda data: data.__setitem__("theme", args.name), args.project)
    emit({"saved": path, "theme": args.name})


def cmd_new(args) -> None:
    settings = Settings()
    emit(
        {
            "configured": settings.configured,
            **workspace.new(settings, args.kind, args.title, args.workspace),
        }
    )


def cmd_list(args) -> None:
    settings = Settings()
    path, exists = workspace.resolve(settings, args.workspace)
    if not path or not exists:
        raise ConfigError("No such workspace. Pass a name under the root, or a path.")
    emit({"workspace": path, "reports": workspace.reports(settings, path)})


def cmd_render(args) -> None:
    settings = Settings()
    if args.spec == "-":
        text = sys.stdin.read()
    else:
        with open(args.spec, encoding="utf-8") as handle:
            text = handle.read()
    try:
        spec = json.loads(text)
    except ValueError as error:
        raise ConfigError(f"The spec isn't valid JSON: {error}") from None
    theme = themes.Theme(args.theme or settings.data["theme"], settings)
    meta = spec.setdefault("meta", {})
    meta.setdefault("updated", workspace.today().isoformat())
    output = os.path.abspath(args.output)
    previous = workspace.read_meta(output) if os.path.exists(output) else None
    meta.setdefault("created", (previous or {}).get("created") or meta["updated"])
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as out:
        out.write(theme.render(spec))
    emit({"written": output, "link": workspace.link(output)})


def cmd_check(args) -> None:
    settings = Settings()
    if not os.path.isfile(args.file):
        raise ConfigError(f"No such file: {args.file}")
    fixed = None
    if args.fix:
        fixed = checker.fix(args.file, themes.Theme(settings.data["theme"], settings))
    problems = checker.check(args.file)
    errors = sum(1 for problem in problems if problem["level"] == "error")
    emit(
        {
            "file": os.path.abspath(args.file),
            "contents_rebuilt": fixed,
            "errors": errors,
            "warnings": len(problems) - errors,
            "problems": problems,
        }
    )
    if errors:
        sys.exit(1)


def _summary(settings: Settings) -> dict:
    return {
        "root": settings.root,
        "layout": settings.data["layout"],
        "theme": settings.data["theme"],
        "kinds": sorted(settings.data["kinds"]),
    }


COMMANDS = {
    "init": cmd_init,
    "config": cmd_config,
    "kind": cmd_kind,
    "layout": cmd_layout,
    "theme": cmd_theme,
    "new": cmd_new,
    "list": cmd_list,
    "render": cmd_render,
    "check": cmd_check,
}
