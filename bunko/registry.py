"""Running servers, so `bunko link` can find the one that serves a path.

Each server writes a small JSON record when it starts and removes it when it
stops. A record whose process is gone, or whose port no longer answers, is
stale and gets cleaned up the next time anyone looks.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import time
from urllib.parse import quote, urlencode

from .storage import runtime_dir, write_private


def _folder() -> str:
    return os.path.join(runtime_dir(), "servers")


def _record_path(pid: int) -> str:
    return os.path.join(_folder(), f"{pid}.json")


def register(root: str, show_hidden: bool, bind: str, port: int, url: str) -> str:
    """Record this process's server, and return the record's path."""
    path = _record_path(os.getpid())
    record = {
        "pid": os.getpid(),
        "root": root,
        "hidden": show_hidden,
        "bind": bind,
        "port": port,
        "url": url,
        "started": round(time.time()),
    }
    write_private(path, json.dumps(record, indent=1))
    return path


def unregister(path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(path)


def running() -> list:
    """Records of the servers that are up right now, removing stale ones."""
    folder = _folder()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    found = []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path) as handle:
                record = json.load(handle)
            alive = _alive(record)
        except (OSError, ValueError, KeyError, TypeError):
            alive = False
        if alive:
            found.append(record)
        else:
            unregister(path)
    return found


def _alive(record: dict) -> bool:
    try:
        os.kill(int(record["pid"]), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # someone else's process with that id: the port check decides
    # A process id can be reused after a crash; a listening port confirms it.
    host = record["bind"]
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    try:
        with socket.create_connection((host, int(record["port"])), timeout=0.5):
            return True
    except OSError:
        return False


def server_for(path: str, records: list):
    """(record, path relative to its root) for the innermost server serving path, or None."""
    best = None
    for candidate in {os.path.abspath(path), os.path.realpath(path)}:
        for record in records:
            root = record["root"]
            try:
                inside = os.path.commonpath([root, candidate]) == root
            except ValueError:
                continue  # different drives on Windows
            if inside and (best is None or len(root) > len(best[0]["root"])):
                rel = os.path.relpath(candidate, root)
                best = (record, "" if rel == "." else rel.replace(os.sep, "/"))
    return best


def is_hidden(rel: str) -> bool:
    return any(part.startswith(".") for part in rel.split("/") if part)


def app_url(base: str, rel: str, line: int | None = None) -> str:
    """The app's URL for a path: base/#/encoded/path, with ?line= for text files."""
    hash_path = "/".join(quote(part, safe="") for part in rel.split("/") if part)
    url = base.rstrip("/") + "/#/" + hash_path
    if line:
        url += "?" + urlencode({"line": line})
    return url


def public_url(bind: str, port: int, mode: str) -> str:
    """The base URL people use to reach a server, as well as bunko can tell."""
    if mode == "tailscale":
        name = _tailscale_name()
        if name:
            # docs/security.md serves HTTPS on the same port number.
            return f"https://{name}:{port}/"
    if bind in ("0.0.0.0", "::"):
        return f"http://{socket.gethostname()}:{port}/"
    if bind in ("127.0.0.1", "::1", "localhost"):
        return f"http://localhost:{port}/"
    host = f"[{bind}]" if ":" in bind else bind
    return f"http://{host}:{port}/"


def _tailscale_name() -> str | None:
    try:
        done = subprocess.run(
            ["tailscale", "status", "--json"], capture_output=True, timeout=3, check=True
        )
        name = json.loads(done.stdout)["Self"]["DNSName"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
    return name.rstrip(".") or None
