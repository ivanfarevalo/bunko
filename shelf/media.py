"""Thumbnails and video metadata, using ffmpeg and ffprobe when installed.

Both are optional. Without ffmpeg the gallery falls back to full-size images
and generic video icons; without ffprobe the video tools estimate frame rate in
the browser.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from collections import OrderedDict

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".ogv"}
SMALL_IMAGE = 96 * 1024  # serve these as they are: a thumbnail would barely help
THUMB_WIDTH = 360
TIMEOUT = 30


def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "shelf")


def kind_of(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def file_url(real: str) -> str:
    # The file: prefix stops ffmpeg reading a name like "-i" or "http:x" as
    # an option or a network address.
    return "file:" + real


class Thumbnails:
    def __init__(self, directory: str | None = None, enabled: bool = True):
        self.ffmpeg = shutil.which("ffmpeg") if enabled else None
        self.directory = os.path.join(directory or cache_dir(), "thumbs")
        # A gallery asks for dozens at once; this keeps ffmpeg from swamping the box.
        self.slots = threading.BoundedSemaphore(max(2, min(4, (os.cpu_count() or 2) // 2)))

    @property
    def available(self) -> bool:
        return self.ffmpeg is not None

    def key(self, real: str, info: os.stat_result) -> str:
        raw = "%s\0%d\0%d\0%d" % (real, info.st_mtime_ns, info.st_size, THUMB_WIDTH)
        return hashlib.sha1(raw.encode("utf-8", "surrogateescape")).hexdigest()

    def get(self, real: str):
        """Return (path to send, is_original) or None when there is no thumbnail."""
        kind = kind_of(real)
        if kind is None:
            return None
        info = os.stat(real)
        if kind == "image" and info.st_size <= SMALL_IMAGE:
            return real, True
        if not self.available:
            return None
        key = self.key(real, info)
        folder = os.path.join(self.directory, key[:2])
        out = os.path.join(folder, key + ".jpg")
        failed = os.path.join(folder, key + ".fail")
        if os.path.exists(out):
            return out, False
        if os.path.exists(failed):
            return None
        with self.slots:
            if os.path.exists(out):  # another request made it while we waited
                return out, False
            os.makedirs(folder, exist_ok=True)
            temp = "%s.%d.%d.jpg" % (out, os.getpid(), threading.get_ident())
            seeks = ("1", "0") if kind == "video" else (None,)
            for seek in seeks:
                if self._run(real, temp, seek) and os.path.getsize(temp) > 0:
                    os.replace(temp, out)
                    return out, False
            for leftover in (temp,):
                if os.path.exists(leftover):
                    os.remove(leftover)
            open(failed, "w").close()
            return None

    def _run(self, real: str, out: str, seek: str | None) -> bool:
        command = [self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        if seek:
            command += ["-ss", seek]
        command += [
            "-i", file_url(real),
            "-frames:v", "1",
            "-vf", "scale=w='min(%d,iw)':h=-2" % THUMB_WIDTH,
            "-q:v", "5",
            out,
        ]
        try:
            done = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return done.returncode == 0 and os.path.exists(out)


class Prober:
    """Video facts for the review tools: frame rate, duration, codec."""

    def __init__(self, enabled: bool = True):
        self.ffprobe = shutil.which("ffprobe") if enabled else None
        self.cache: OrderedDict = OrderedDict()
        self.lock = threading.Lock()

    def probe(self, real: str) -> dict | None:
        if not self.ffprobe:
            return None
        info = os.stat(real)
        key = (real, info.st_mtime_ns, info.st_size)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
        command = [
            self.ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames:format=duration",
            "-of", "json", file_url(real),
        ]
        try:
            done = subprocess.run(command, capture_output=True, timeout=TIMEOUT)
            data = json.loads(done.stdout or b"{}")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
        stream = (data.get("streams") or [{}])[0]
        result = {
            "codec": stream.get("codec_name"),
            "width": stream.get("width"),
            "height": stream.get("height"),
            "fps": self._rate(stream.get("avg_frame_rate")) or self._rate(stream.get("r_frame_rate")),
            "frames": int(stream["nb_frames"]) if str(stream.get("nb_frames", "")).isdigit() else None,
            "duration": float(data.get("format", {}).get("duration") or 0) or None,
        }
        with self.lock:
            self.cache[key] = result
            while len(self.cache) > 2000:
                self.cache.popitem(last=False)
        return result

    @staticmethod
    def _rate(text) -> float | None:
        try:
            top, bottom = str(text).split("/")
            value = float(top) / float(bottom)
        except (ValueError, ZeroDivisionError):
            return None
        return round(value, 3) if 0 < value < 1000 else None
