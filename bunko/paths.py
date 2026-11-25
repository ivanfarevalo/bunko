"""The served folder, and the rules for which paths inside it may be read."""

from __future__ import annotations

import os
import re


class Blocked(Exception):
    """A path that must look like it doesn't exist."""


class Root:
    """The served directory.

    Paths are relative, slash-separated, and checked by `resolve` before any
    file is touched. Dotfiles stay hidden unless `show_hidden` is set, including
    when a symlink points at one.
    """

    def __init__(self, path: str, show_hidden: bool = False):
        self.real = os.path.realpath(path)
        self.show_hidden = show_hidden

    def allowed_target(self, real: str) -> bool:
        """Whether a symlink may land on `real`.

        Symlinks may leave the root, as with http.server, because data often
        lives on another disk. They may not reach a dotfile. Only the part of
        the target below where it leaves the root counts, so serving a folder
        that is itself inside a dot-directory still works.
        """
        if self.show_hidden:
            return True
        below = real[len(os.path.commonpath([self.real, real])) :]
        return not any(part.startswith(".") for part in below.split(os.sep))

    def resolve(self, rel: str) -> str:
        """The real path for a relative one, or `Blocked`."""
        parts = [part for part in rel.split("/") if part not in ("", ".")]
        if ".." in parts or "\x00" in rel or any(os.sep in part for part in parts):
            raise Blocked(rel)
        if not self.show_hidden and any(part.startswith(".") for part in parts):
            raise Blocked(rel)
        real = os.path.realpath(os.path.join(self.real, *parts))
        if not self.allowed_target(real):
            raise Blocked(rel)
        return real

    def visible(self, name: str) -> bool:
        """Whether a directory entry with this name is listed at all."""
        return is_utf8(name) and (self.show_hidden or not name.startswith("."))


def is_utf8(name: str) -> bool:
    """Names that aren't valid UTF-8 can't round-trip through a URL, so they're skipped."""
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _chunks(text: str) -> list:
    return [
        (0, int(part), "") if part.isdecimal() else (1, 0, part)
        for part in re.split(r"(\d+)", text.lower())
        if part
    ]


def natural_key(name: str) -> tuple:
    """Sort key that puts frame_2 before frame_10, and clip.mp4 before clip2.webm."""
    stem, ext = os.path.splitext(name)
    return _chunks(stem), _chunks(ext)
