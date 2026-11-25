"""Recent files, favorites and tags: the sidebar's "places".

Kept on the server, so they follow a person between browsers and devices, in
~/.config/bunko/state/<root>.json. Nothing is written to the served folder.
Each Tailscale user gets their own lists; open and token modes share one set.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time

from .paths import Blocked
from .storage import config_dir, write_private

RECENT_KEEP = 50
FAVORITES_MAX = 500
TAGS_MAX = 100
TAGGED_MAX = 2000  # tagged paths per tag
TAG_NAME = re.compile(r"^[^\x00-\x1f/\\]{1,40}$")
NICKNAME_MAX = 60


class PlaceError(ValueError):
    """A request the store refuses, with a message for the user."""


def clean_nickname(name) -> str:
    """A favorite's display name. Empty means "use the file name"."""
    name = " ".join(str(name or "").split())
    if len(name) > NICKNAME_MAX or any(ord(char) < 32 for char in name):
        raise PlaceError(f"Nicknames are up to {NICKNAME_MAX} characters.")
    return name


def clean_tag(name) -> str:
    name = " ".join(str(name or "").split())
    if not TAG_NAME.match(name):
        raise PlaceError("Tags are 1 to 40 characters, without slashes.")
    return name


# Each change's "op", and the Places method that applies it.
_OPS = {
    "visit": "_visit",
    "forget": "_forget",
    "clear-recent": "_clear_recent",
    "favorite": "_favorite",
    "rename-favorite": "_rename_favorite",
    "move-favorite": "_move_favorite",
    "tag": "_tag",
    "untag": "_untag",
    "rename-tag": "_rename_tag",
    "delete-tag": "_delete_tag",
}


class Places:
    """The places for one served folder, stored as JSON with a section per user."""

    def __init__(self, root, directory: str | None = None):
        self.root = root
        folder = directory or os.path.join(config_dir(), "state")
        key = hashlib.sha1(root.real.encode("utf-8", "surrogateescape")).hexdigest()[:16]
        self.path = os.path.join(folder, key + ".json")
        self.lock = threading.Lock()
        self.data = self._load()

    # -- storage ---------------------------------------------------------

    def _load(self) -> dict:
        try:
            with open(self.path) as handle:
                data = json.load(handle)
            if isinstance(data, dict) and isinstance(data.get("users"), dict):
                return data
        except (OSError, ValueError):
            pass
        return {"root": self.root.real, "users": {}}

    def _save(self) -> None:
        write_private(self.path, json.dumps(self.data, indent=1, sort_keys=True))

    def _user(self, user: str | None) -> dict:
        key = (user or "default").lower()
        entry = self.data["users"].setdefault(key, {})
        entry.setdefault("recent", [])
        entry.setdefault("favorites", [])
        entry.setdefault("tags", {})
        entry.setdefault("nicknames", {})
        return entry

    # -- paths -----------------------------------------------------------

    def _check(self, path) -> str:
        """Normalize a path and make sure it's one the server would serve."""
        path = "/".join(part for part in str(path or "").split("/") if part not in ("", "."))
        if not path:
            raise PlaceError("Choose a file or folder.")
        try:
            real = self.root.resolve(path)
        except Blocked:
            raise PlaceError("That path isn't available.") from None
        if not os.path.exists(real):
            raise PlaceError("That path doesn't exist.")
        return path

    def _describe(self, path: str):
        """An entry for the client, or None when the path must stay invisible."""
        try:
            real = self.root.resolve(path)
        except Blocked:
            return None  # a dotfile saved while --hidden was on
        exists = os.path.exists(real)
        return {"path": path, "dir": exists and os.path.isdir(real), "missing": not exists}

    # -- reading ---------------------------------------------------------

    def view(self, user: str | None) -> dict:
        with self.lock:
            entry = self._user(user)
            recent = [dict(item) for item in entry["recent"]]
            favorites = list(entry["favorites"])
            nicknames = dict(entry["nicknames"])
            tags = {name: list(paths) for name, paths in entry["tags"].items()}
        out_recent = []
        for item in recent:
            described = self._describe(item["path"])
            if described and not described["missing"]:  # gone files just drop off
                described["at"] = item["at"]
                out_recent.append(described)
        out_tags = []
        for name in sorted(tags, key=str.lower):
            files = [d for d in map(self._describe, tags[name]) if d]
            out_tags.append({"name": name, "files": files})
        tagged = {}
        for tag in out_tags:
            for item in tag["files"]:
                tagged.setdefault(item["path"], []).append(tag["name"])
        return {
            "recent": out_recent,
            "favorites": [
                dict(d, name=nicknames[d["path"]]) if d["path"] in nicknames else d
                for d in map(self._describe, favorites)
                if d
            ],
            "tags": out_tags,
            "tagged": tagged,
        }

    # -- changes ---------------------------------------------------------

    def apply(self, user: str | None, change: dict) -> dict:
        """Apply one change, such as {"op": "favorite", "path": "a.md"}, and return the new view."""
        op = _OPS.get(change.get("op"))
        if op is None:
            raise PlaceError("Unknown change.")
        with self.lock:
            getattr(self, op)(self._user(user), change)
            self._save()
        return self.view(user)

    def _visit(self, entry: dict, change: dict) -> None:
        path = self._check(change.get("path"))
        entry["recent"] = [item for item in entry["recent"] if item["path"] != path]
        entry["recent"].insert(0, {"path": path, "at": round(time.time(), 1)})
        del entry["recent"][RECENT_KEEP:]

    def _forget(self, entry: dict, change: dict) -> None:
        path = _text(change, "path")
        entry["recent"] = [item for item in entry["recent"] if item["path"] != path]

    def _clear_recent(self, entry: dict, change: dict) -> None:
        entry["recent"] = []

    def _favorite(self, entry: dict, change: dict) -> None:
        if not change.get("on", True):
            path = _text(change, "path")
            entry["favorites"] = [item for item in entry["favorites"] if item != path]
            entry["nicknames"].pop(path, None)
            return
        path = self._check(change.get("path"))
        if path not in entry["favorites"]:
            if len(entry["favorites"]) >= FAVORITES_MAX:
                raise PlaceError(f"That's the most favorites bunko keeps ({FAVORITES_MAX}).")
            entry["favorites"].append(path)
        if "name" in change:
            _set_nickname(entry, path, change["name"])

    def _rename_favorite(self, entry: dict, change: dict) -> None:
        path = _text(change, "path")
        if path not in entry["favorites"]:
            raise PlaceError("Only favorites have nicknames.")
        _set_nickname(entry, path, change.get("name"))

    def _move_favorite(self, entry: dict, change: dict) -> None:
        path = _text(change, "path")
        favorites = entry["favorites"]
        if path in favorites:
            favorites.remove(path)
            index = max(0, min(int(change.get("index", 0)), len(favorites)))
            favorites.insert(index, path)

    def _tag(self, entry: dict, change: dict) -> None:
        path = self._check(change.get("path"))
        name = clean_tag(change.get("tag"))
        tags = entry["tags"]
        existing = _find_tag(tags, name)
        if existing is None:
            if len(tags) >= TAGS_MAX:
                raise PlaceError(f"That's the most tags bunko keeps ({TAGS_MAX}).")
            existing = name
            tags[name] = []
        if path not in tags[existing]:
            if len(tags[existing]) >= TAGGED_MAX:
                raise PlaceError(f"That tag is full ({TAGGED_MAX} items).")
            tags[existing].append(path)

    def _untag(self, entry: dict, change: dict) -> None:
        name, path = _text(change, "tag"), _text(change, "path")
        tags = entry["tags"]
        if name in tags:
            tags[name] = [item for item in tags[name] if item != path]
            if not tags[name]:
                del tags[name]

    def _rename_tag(self, entry: dict, change: dict) -> None:
        old = _text(change, "tag")
        new = clean_tag(change.get("name"))
        tags = entry["tags"]
        if old not in tags:
            raise PlaceError(f"No tag named {old!r}.")
        clash = _find_tag(tags, new, besides=old)
        moved = tags.pop(old)
        if clash:  # renaming onto an existing tag merges the two
            tags[clash] += [path for path in moved if path not in tags[clash]]
        else:
            tags[new] = moved

    def _delete_tag(self, entry: dict, change: dict) -> None:
        entry["tags"].pop(_text(change, "tag"), None)


def _text(change: dict, key: str) -> str:
    return str(change.get(key) or "")


def _find_tag(tags: dict, name: str, besides: str | None = None) -> str | None:
    """The existing tag that matches name, ignoring case."""
    return next((tag for tag in tags if tag.lower() == name.lower() and tag != besides), None)


def _set_nickname(entry: dict, path: str, name) -> None:
    name = clean_nickname(name)
    if name and name != path.rsplit("/", 1)[-1]:
        entry["nicknames"][path] = name
    else:
        entry["nicknames"].pop(path, None)  # empty, or the file name again
