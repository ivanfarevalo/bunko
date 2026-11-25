"""Search inside files.

Uses ripgrep when installed (fast, skips binaries), else a pure-Python scan of
the name index. Either way every hit passes the same access check as a file
request, so a symlink cannot leak a dotfile's contents into results.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time

LIMIT = 300  # matching lines per search
PER_FILE = 5  # matching lines per file
MAX_FILE_RG = 64 * 1024 * 1024  # ripgrep reads big logs quickly; matches the UI's jump-to-line reach
MAX_FILE_PY = 5 * 1024 * 1024  # the Python fallback is slower, so it skips sooner
BUDGET = 12.0  # seconds before a search stops and returns what it has
SNIPPET = 220  # characters of context per line
SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif", ".tif", ".tiff",
    ".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".mp3", ".wav", ".flac", ".ogg",
    ".zip", ".gz", ".tgz", ".xz", ".bz2", ".7z", ".tar", ".pdf", ".pt", ".pth", ".onnx",
    ".bin", ".npy", ".npz", ".pkl", ".so", ".o", ".a", ".whl", ".pyc", ".parquet", ".h5",
}


def snippet(line: str, start: int, end: int):
    """Trim a long line to a window around the first match."""
    line = line.rstrip("\r\n")
    if len(line) <= SNIPPET:
        return line, 0
    left = max(0, min(start - SNIPPET // 3, len(line) - SNIPPET))
    return line[left:left + SNIPPET], left


class ContentSearch:
    def __init__(self, root, index, skip_dirs):
        self.root = root
        self.index = index
        self.skip_dirs = skip_dirs
        self.rg = shutil.which("rg")
        # Searches read a lot of disk; two at a time is plenty.
        self.slots = threading.BoundedSemaphore(2)

    @property
    def engine(self) -> str:
        return "ripgrep" if self.rg else "python"

    def search(self, query: str) -> dict:
        query = query.strip()
        if len(query) < 2:
            return {"results": [], "engine": self.engine, "truncated": False, "partial": False}
        started = time.monotonic()
        with self.slots:
            if self.rg:
                hits, partial = self._ripgrep(query)
            else:
                hits, partial = self._python(query)
        return {
            "results": hits,
            "engine": self.engine,
            "truncated": len(hits) >= LIMIT,
            "partial": partial,
            "seconds": round(time.monotonic() - started, 2),
        }

    def _allowed(self, rel: str) -> bool:
        try:
            self.root.resolve(rel)
        except Exception:
            return False
        return True

    def _hit(self, rel, number, line, spans):
        if not spans:
            return None
        text, shift = snippet(line, spans[0][0], spans[0][1])
        marks = [[max(s - shift, 0), min(e - shift, len(text))] for s, e in spans if e - shift > 0 and s - shift < len(text)]
        return {"path": rel, "line": number, "text": text, "marks": marks}

    def _ripgrep(self, query: str):
        command = [
            self.rg, "--json", "--fixed-strings", "--ignore-case", "--follow", "--no-ignore",
            "--max-count", str(PER_FILE), "--max-filesize", str(MAX_FILE_RG),
            "--max-columns", "2000", "--max-columns-preview",
        ]
        if self.root.show_hidden:
            command.append("--hidden")
        for name in self.skip_dirs:
            command += ["--glob", "!**/%s/**" % name]
        command += ["--", query, "."]
        hits = []
        partial = False
        deadline = time.monotonic() + BUDGET
        process = subprocess.Popen(command, cwd=self.root.real, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            for raw in process.stdout:
                if time.monotonic() > deadline:
                    partial = True
                    break
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if event.get("type") != "match":
                    continue
                data = event["data"]
                rel = data["path"].get("text")
                line = data["lines"].get("text")
                if rel is None or line is None:  # not valid UTF-8
                    continue
                rel = rel[2:] if rel.startswith("./") else rel
                if not self._allowed(rel):
                    continue
                encoded = line.encode("utf-8", "surrogateescape")
                spans = [
                    (len(encoded[: m["start"]].decode("utf-8", "replace")),
                     len(encoded[: m["end"]].decode("utf-8", "replace")))
                    for m in data.get("submatches", [])
                ]
                hit = self._hit(rel, data.get("line_number"), line, spans)
                if hit:
                    hits.append(hit)
                if len(hits) >= LIMIT:
                    break
        finally:
            process.kill()
            process.wait()
        return hits, partial

    def _python(self, query: str):
        needle = query.lower()
        hits = []
        partial = False
        deadline = time.monotonic() + BUDGET
        for rel, _lowered in list(self.index.paths):
            if rel.endswith("/") or os.path.splitext(rel)[1].lower() in SKIP_EXTS:
                continue
            if time.monotonic() > deadline:
                partial = True
                break
            try:
                real = self.root.resolve(rel)
                if os.path.getsize(real) > MAX_FILE_PY:
                    continue
                with open(real, "rb") as handle:
                    data = handle.read()
            except Exception:
                continue
            if b"\0" in data[:8192]:
                continue
            text = data.decode("utf-8", "replace")
            if needle not in text.lower():
                continue
            found = 0
            for number, line in enumerate(text.split("\n"), 1):
                lower = line.lower()
                at = lower.find(needle)
                if at < 0:
                    continue
                spans = []
                while at >= 0 and len(spans) < 10:
                    spans.append((at, at + len(needle)))
                    at = lower.find(needle, at + len(needle))
                hits.append(self._hit(rel, number, line, spans))
                found += 1
                if found >= PER_FILE or len(hits) >= LIMIT:
                    break
            if len(hits) >= LIMIT:
                break
        return hits, partial
