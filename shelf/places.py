"""Recent files, favorites and tags: the sidebar's "places".

Kept on the server, so they follow a person between browsers and devices, in
~/.config/shelf/state/<root>.json. Nothing is written to the served folder.
Each Tailscale user gets their own lists; open and token modes share one set.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time

from .access import config_dir

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
        raise PlaceError("Nicknames are up to %d characters." % NICKNAME_MAX)
    return name


def clean_tag(name) -> str:
    name = " ".join(str(name or "").split())
    if not TAG_NAME.match(name):
        raise PlaceError("Tags are 1 to 40 characters, without slashes.")
    return name


class Places:
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
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        temp = self.path + ".tmp"
        handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w") as out:
            json.dump(self.data, out, indent=1, sort_keys=True)
        os.replace(temp, self.path)

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
        except Exception:
            raise PlaceError("That path isn't available.")
        if not os.path.exists(real):
            raise PlaceError("That path doesn't exist.")
        return path

    def _describe(self, path: str):
        """An entry for the client, or None when the path must stay invisible."""
        try:
            real = self.root.resolve(path)
        except Exception:
            return None  # e.g. dotfiles, since --hidden was turned off
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
                for d in map(self._describe, favorites) if d
            ],
            "tags": out_tags,
            "tagged": tagged,
        }

    # -- changes ---------------------------------------------------------

    @staticmethod
    def _nickname(entry: dict, path: str, name) -> None:
        name = clean_nickname(name)
        if name and name != path.rsplit("/", 1)[-1]:
            entry["nicknames"][path] = name
        else:
            entry["nicknames"].pop(path, None)  # empty, or just the file name again

    def apply(self, user: str | None, change: dict) -> dict:
        op = change.get("op")
        with self.lock:
            entry = self._user(user)
            if op == "visit":
                path = self._check(change.get("path"))
                entry["recent"] = [item for item in entry["recent"] if item["path"] != path]
                entry["recent"].insert(0, {"path": path, "at": round(time.time(), 1)})
                del entry["recent"][RECENT_KEEP:]
            elif op == "forget":
                path = str(change.get("path") or "")
                entry["recent"] = [item for item in entry["recent"] if item["path"] != path]
            elif op == "clear-recent":
                entry["recent"] = []
            elif op == "favorite":
                if change.get("on", True):
                    path = self._check(change.get("path"))
                    if path not in entry["favorites"]:
                        if len(entry["favorites"]) >= FAVORITES_MAX:
                            raise PlaceError("That's the most favorites shelf keeps (%d)." % FAVORITES_MAX)
                        entry["favorites"].append(path)
                    if "name" in change:
                        self._nickname(entry, path, change["name"])
                else:
                    path = str(change.get("path") or "")
                    entry["favorites"] = [item for item in entry["favorites"] if item != path]
                    entry["nicknames"].pop(path, None)  # the nickname belongs to the favorite
            elif op == "rename-favorite":
                path = str(change.get("path") or "")
                if path not in entry["favorites"]:
                    raise PlaceError("Only favorites have nicknames.")
                self._nickname(entry, path, change.get("name"))
            elif op == "move-favorite":
                path = str(change.get("path") or "")
                if path in entry["favorites"]:
                    entry["favorites"].remove(path)
                    index = max(0, min(int(change.get("index", 0)), len(entry["favorites"])))
                    entry["favorites"].insert(index, path)
            elif op == "tag":
                path = self._check(change.get("path"))
                name = clean_tag(change.get("tag"))
                existing = next((tag for tag in entry["tags"] if tag.lower() == name.lower()), None)
                if existing is None:
                    if len(entry["tags"]) >= TAGS_MAX:
                        raise PlaceError("That's the most tags shelf keeps (%d)." % TAGS_MAX)
                    entry["tags"][name] = []
                    existing = name
                paths = entry["tags"][existing]
                if path not in paths:
                    if len(paths) >= TAGGED_MAX:
                        raise PlaceError("That tag is full (%d items)." % TAGGED_MAX)
                    paths.append(path)
            elif op == "untag":
                name = str(change.get("tag") or "")
                path = str(change.get("path") or "")
                if name in entry["tags"]:
                    entry["tags"][name] = [item for item in entry["tags"][name] if item != path]
                    if not entry["tags"][name]:
                        del entry["tags"][name]
            elif op == "rename-tag":
                old = str(change.get("tag") or "")
                new = clean_tag(change.get("name"))
                if old not in entry["tags"]:
                    raise PlaceError("No tag named %r." % old)
                clash = next((tag for tag in entry["tags"] if tag.lower() == new.lower() and tag != old), None)
                moved = entry["tags"].pop(old)
                if clash:  # renaming onto an existing tag merges them
                    entry["tags"][clash] += [path for path in moved if path not in entry["tags"][clash]]
                else:
                    entry["tags"][new] = moved
            elif op == "delete-tag":
                entry["tags"].pop(str(change.get("tag") or ""), None)
            else:
                raise PlaceError("Unknown change.")
            self._save()
        return self.view(user)
