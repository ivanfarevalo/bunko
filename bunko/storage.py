"""Where bunko keeps its own files: config, state, and caches. Never the served folder."""

from __future__ import annotations

import os


def _xdg(variable: str, fallback: str) -> str:
    return os.environ.get(variable) or os.path.join(os.path.expanduser("~"), fallback)


def config_home() -> str:
    return _xdg("XDG_CONFIG_HOME", ".config")


def config_dir() -> str:
    return os.path.join(config_home(), "bunko")


def cache_dir() -> str:
    return os.path.join(_xdg("XDG_CACHE_HOME", ".cache"), "bunko")


def runtime_dir() -> str:
    """For files that only matter while bunko runs: per user, and cleared at logout where possible."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return os.path.join(runtime, "bunko") if runtime else os.path.join(cache_dir(), "run")


def write_private(path: str, text: str) -> None:
    """Replace a file atomically, readable only by its owner from the start."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    temp = path + ".tmp"
    handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as out:
        out.write(text)
    os.replace(temp, path)
