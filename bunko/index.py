"""Search by name: every path under the root, kept in memory."""

from __future__ import annotations

import heapq
import os
import threading
import time

from .paths import Root

FRESH_FOR = 120  # seconds before a search triggers a rebuild in the background
MAX_PATHS = 2_000_000
MAX_RESULTS = 100
SKIP_DIRS = frozenset({"node_modules", "__pycache__", "site-packages", "venv"})


class SearchIndex:
    """A list of (path, lowercased path), rebuilt in the background when stale.

    Folders end in "/". During the first build the list fills in place, so
    searches work before the walk finishes.
    """

    def __init__(self, root: Root):
        self.root = root
        self.lock = threading.Lock()
        self.paths: list = []
        self.building = False
        self.built_at = 0.0
        self.truncated = False

    def refresh(self) -> None:
        """Start a rebuild if the index is stale and none is running."""
        with self.lock:
            if self.building or time.time() - self.built_at < FRESH_FOR:
                return
            self.building = True
        threading.Thread(target=self._build, daemon=True).start()

    def status(self) -> dict:
        self.refresh()
        return {"indexed": len(self.paths), "indexing": self.building, "truncated": self.truncated}

    def search(self, query: str) -> list:
        """Paths containing every word of the query, best name matches first."""
        tokens = query.lower().split()
        if not tokens:
            return []
        self.refresh()
        last = tokens[-1]
        hits = []
        for order, (path, lowered) in enumerate(list(self.paths)):
            if all(token in lowered for token in tokens):
                name = lowered.rstrip("/").rsplit("/", 1)[-1]
                hits.append((_rank(name, last), len(path), order, path))
        return [hit[3] for hit in heapq.nsmallest(MAX_RESULTS, hits)]

    def _build(self) -> None:
        found: list = []
        if not self.built_at:
            self.paths = found
        try:
            self.truncated = self._walk(found)
        finally:
            self.paths = found
            self.built_at = time.time()
            self.building = False

    def _walk(self, found: list) -> bool:
        """Fill `found`; return True if it stopped at MAX_PATHS."""
        seen = {self.root.real}
        stack = [(self.root.real, "")]
        while stack:
            real, rel = stack.pop()
            try:
                entries = list(os.scandir(real))
            except OSError:
                continue
            for entry in entries:
                if not self.root.visible(entry.name):
                    continue
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    continue
                target = entry.path
                if entry.is_symlink():
                    target = os.path.realpath(entry.path)
                    if not self.root.allowed_target(target):
                        continue
                if len(found) >= MAX_PATHS:
                    return True
                child = rel + entry.name
                if not is_dir:
                    found.append((child, child.lower()))
                    continue
                found.append((child + "/", child.lower()))
                if entry.name not in SKIP_DIRS and target not in seen:
                    seen.add(target)  # also stops symlink loops
                    stack.append((target, child + "/"))
        return False


def _rank(name: str, word: str) -> int:
    if name == word:
        return 0
    if name.startswith(word):
        return 1
    return 2 if word in name else 3
