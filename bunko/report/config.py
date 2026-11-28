"""Report settings: built-in defaults, then the user's file, then the project's.

User settings live in ~/.config/bunko/report.json, and a project can override
them with .bunko/report.json in its folder or any parent, as Git layers its
config. Kinds and layouts merge by name, so adding one never hides the others.
"""

from __future__ import annotations

import copy
import json
import os

from ..storage import config_dir, write_private

FILE = "report.json"
PROJECT_DIR = ".bunko"

DEFAULT_KINDS = {
    "results": {
        "description": "Results of an experiment or analysis: what was measured, the numbers, what they mean.",
        "guidance": "Lead with the answer. Tables and charts come from the data, through the builder script, so the report can be rebuilt.",
        "sections": ["Summary", "Setup", "Results", "Discussion", "Next steps"],
        "builder": True,
    },
    "write-up": {
        "description": "A record of a working session: what was discussed, decided, and done, and why.",
        "guidance": "Decisions first, then the reasoning. Link to the files and commits involved.",
        "sections": ["Summary", "Decisions", "What was done", "Open questions"],
        "builder": False,
    },
    "explainer": {
        "description": "Teaches how something works, for someone new to it.",
        "guidance": "Build up from what the reader knows. Use diagrams and short examples.",
        "sections": ["Overview", "How it works", "Example", "Takeaways"],
        "builder": False,
    },
}

DEFAULT_LAYOUTS = {
    "simple": {
        "description": "One folder per workspace, with its reports inside.",
        "folder": "{slug}",
        "subdirs": [],
        "places": {},
    },
    "experiment": {
        "description": "Dated experiment folders with code, configs, data, runs, results, and reports apart.",
        "folder": "{date}_{slug}",
        "subdirs": ["src", "configs", "data", "runs", "results", "report", "notes"],
        "places": {"results": "", "write-up": "notes", "*": "report"},
    },
}

DEFAULTS = {
    "root": "~/reports",
    "layout": "simple",
    "theme": "house",
    "kinds": DEFAULT_KINDS,
    "layouts": DEFAULT_LAYOUTS,
}

SCALARS = ("root", "layout", "theme")


class ConfigError(ValueError):
    """A setting that can't be used, with a message for the user."""


def user_path() -> str:
    return os.path.join(config_dir(), FILE)


def project_path(start: str | None = None) -> str | None:
    """The nearest .bunko/report.json at or above `start`, if any."""
    folder = os.path.abspath(start or os.getcwd())
    while True:
        candidate = os.path.join(folder, PROJECT_DIR, FILE)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        folder = parent


def read(path: str | None) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise ConfigError(f"Can't read {path}: {error}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a JSON object")
    return data


def write(path: str, data: dict, private: bool = True) -> None:
    """User settings are private; a project's are shared with whoever shares the project."""
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if private:
        write_private(path, text)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w") as out:
        out.write(text)
    os.replace(temp, path)


def merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key in ("kinds", "layouts") and isinstance(value, dict):
            out.setdefault(key, {})
            for name, entry in value.items():
                if entry is None:
                    out[key].pop(name, None)  # a project can remove a kind
                else:
                    out[key][name] = entry
        else:
            out[key] = value
    return out


class Settings:
    """The effective settings, and where each layer comes from."""

    def __init__(self, start: str | None = None):
        self.user_file = user_path()
        self.project_file = project_path(start)
        self.user = read(self.user_file)
        self.project = read(self.project_file)
        self.data = merge(merge(DEFAULTS, self.user), self.project)

    @property
    def configured(self) -> bool:
        return bool(self.user or self.project)

    @property
    def root(self) -> str:
        """Absolute. A relative root is relative to the project folder that set it, or to home."""
        root = os.path.expanduser(self.data["root"])
        if os.path.isabs(root):
            return os.path.normpath(root)
        if "root" in self.project and self.project_file:
            base = os.path.dirname(os.path.dirname(self.project_file))
        else:
            base = os.path.expanduser("~")
        return os.path.normpath(os.path.join(base, root))

    def kind(self, name: str) -> dict:
        kind = self.data["kinds"].get(name)
        if kind is None:
            known = ", ".join(sorted(self.data["kinds"]))
            raise ConfigError(f"No report kind named {name!r}. Known kinds: {known}")
        return kind

    def layout(self, name: str | None = None) -> dict:
        name = name or self.data["layout"]
        layout = self.data["layouts"].get(name)
        if layout is None:
            known = ", ".join(sorted(self.data["layouts"]))
            raise ConfigError(f"No layout named {name!r}. Known layouts: {known}")
        return layout

    def place(self, kind: str) -> str:
        """The folder, inside a workspace, where reports of this kind go."""
        explicit = self.kind(kind).get("place")
        if explicit is not None:
            return explicit
        places = self.layout().get("places", {})
        return places.get(kind, places.get("*", ""))


def update(change, project: bool = False, start: str | None = None) -> str:
    """Apply change(data) to the user or project file, and return the file's path."""
    if project:
        path = project_path(start) or os.path.join(
            os.path.abspath(start or os.getcwd()), PROJECT_DIR, FILE
        )
    else:
        path = user_path()
    data = read(path)
    change(data)
    write(path, data, private=not project)
    return path
