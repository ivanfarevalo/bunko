"""shelf: a read-only file server with a Notion-style browser UI.

Standard library only, so it runs anywhere python3 does. Files stay at their
natural URLs (/a/b.png), exactly like `python -m http.server`, so curl, wget and
absolute links inside served HTML keep working. The app lives at `/` and routes
with the URL hash (/#/a/b.md); its assets and API sit under /__shelf/.
"""
from __future__ import annotations

import email.utils
import hashlib
import heapq
import json
import mimetypes
import os
import pkgutil
import re
import socket
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape as html_escape
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__
from .access import DENIED_PAGE, LOGIN_PAGE, PAGE_CSP, Access
from .office import Office, OfficeError
from .places import PlaceError

PREFIX = "/__shelf/"
DEFAULT_PORT = 8000
CHUNK = 256 * 1024
INDEX_TTL = 120  # seconds a search index stays fresh
INDEX_MAX = 2_000_000  # paths held in memory
SEARCH_LIMIT = 100
SKIP_DIRS = {"node_modules", "__pycache__", "site-packages", "venv"}

# Types mimetypes misses or guesses badly. Anything else that is really text
# still renders, because the UI sniffs content rather than trusting this.
MIME_OVERRIDES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".log": "text/plain",
    ".yaml": "text/plain",
    ".yml": "text/plain",
    ".toml": "text/plain",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".jsonl": "text/plain",
    ".ts": "text/plain",
    ".tsx": "text/plain",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mov": "video/mp4",  # Chrome refuses video/quicktime but plays most .mov
    ".m4v": "video/mp4",
    ".flac": "audio/flac",
    ".opus": "audio/ogg",
    ".avif": "image/avif",
    ".webp": "image/webp",
}

SHELL_CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src * data: blob:; "
    "media-src *; frame-src 'self'; object-src 'none'; base-uri 'none'"
)

# Served to a frame that follows a link to a folder. The app sees this title and
# opens the folder itself.
FRAME_FOLDER_PAGE = b"<!doctype html><title>shelf:folder</title>"


def _chunks(text: str):
    return [
        (0, int(part), "") if part.isdecimal() else (1, 0, part)
        for part in re.split(r"(\d+)", text.lower())
        if part
    ]


def natural_key(name: str):
    """Sort key that puts frame_2 before frame_10.

    The name without its extension compares first, so clip.mp4 sorts before
    clip2.webm, as in most file browsers.
    """
    stem, ext = os.path.splitext(name)
    return _chunks(stem), _chunks(ext)


def is_utf8(name: str) -> bool:
    try:
        name.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def content_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    kind = MIME_OVERRIDES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
    if kind.startswith("text/") or kind in ("application/json", "application/javascript"):
        kind += "; charset=utf-8"
    return kind


def parse_range(header: str, size: int):
    """Return (start, end) inclusive, None to ignore the header, or "invalid".

    Multi-range requests are ignored, which RFC 9110 allows: the client gets
    the whole file.
    """
    match = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", header)
    if not match:
        return None
    first, last = match.groups()
    if not first and not last:
        return None
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
        if start >= size or (last and int(last) < start):
            return "invalid"
        return start, end
    length = int(last)
    if length == 0 or size == 0:
        return "invalid"
    return max(size - length, 0), size - 1


class Blocked(Exception):
    """A path that must look like it does not exist."""


class Root:
    """The served directory and the rules for what may leave it."""

    def __init__(self, path: str, show_hidden: bool):
        self.real = os.path.realpath(path)
        self.show_hidden = show_hidden

    def allowed_target(self, real: str) -> bool:
        """Check where a path really lands, after following symlinks.

        Symlinks may leave the root, as they can with http.server, because
        experiment folders often live on other disks. They may not be a way
        around the dotfile rule, e.g. notes -> ~/.ssh. Only the part below where
        the two paths diverge counts: serving from inside a dot-directory means
        that directory is no secret from you.
        """
        if self.show_hidden:
            return True
        below = real[len(os.path.commonpath([self.real, real])) :]
        return not any(part.startswith(".") for part in below.split(os.sep))

    def resolve(self, rel: str) -> str:
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if ".." in parts or "\x00" in rel or any(os.sep in p for p in parts):
            raise Blocked(rel)
        if not self.show_hidden and any(p.startswith(".") for p in parts):
            raise Blocked(rel)
        real = os.path.realpath(os.path.join(self.real, *parts))
        if not self.allowed_target(real):
            raise Blocked(rel)
        return real


class SearchIndex:
    """In-memory list of every path, rebuilt in the background when stale."""

    def __init__(self, root: Root):
        self.root = root
        self.lock = threading.Lock()
        self.paths: list = []  # complete, or the partial list during the first build
        self.building = False
        self.built_at = 0.0
        self.truncated = False

    def refresh(self) -> None:
        with self.lock:
            if self.building or time.time() - self.built_at < INDEX_TTL:
                return
            self.building = True
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self) -> None:
        found: list = []
        first_build = not self.built_at
        if first_build:
            self.paths = found  # searchable while it fills
        seen = {self.root.real}
        stack = [(self.root.real, "")]
        truncated = False
        try:
            while stack:
                real, rel = stack.pop()
                try:
                    entries = list(os.scandir(real))
                except OSError:
                    continue
                for entry in entries:
                    name = entry.name
                    if (name.startswith(".") and not self.root.show_hidden) or not is_utf8(name):
                        continue
                    child = rel + name
                    try:
                        is_dir = entry.is_dir()
                    except OSError:
                        continue
                    if entry.is_symlink():
                        target = os.path.realpath(entry.path)
                        if not self.root.allowed_target(target):
                            continue
                    else:
                        target = entry.path
                    if len(found) >= INDEX_MAX:
                        truncated = True
                        stack.clear()
                        break
                    if is_dir:
                        found.append((child + "/", child.lower()))
                        if name not in SKIP_DIRS and target not in seen:
                            seen.add(target)  # also breaks symlink loops
                            stack.append((target, child + "/"))
                    else:
                        found.append((child, child.lower()))
        finally:
            self.paths = found
            self.truncated = truncated
            self.built_at = time.time()
            self.building = False

    def search(self, query: str) -> list:
        tokens = query.lower().split()
        if not tokens:
            return []
        self.refresh()
        hits = []
        for order, (path, lowered) in enumerate(list(self.paths)):
            if all(token in lowered for token in tokens):
                base = lowered.rstrip("/").rsplit("/", 1)[-1]
                last = tokens[-1]
                if base == last:
                    rank = 0
                elif base.startswith(last):
                    rank = 1
                elif last in base:
                    rank = 2
                else:
                    rank = 3
                hits.append((rank, len(path), order, path))
        return [hit[3] for hit in heapq.nsmallest(SEARCH_LIMIT, hits)]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "shelf/" + __version__
    timeout = 120
    root: Root
    index: SearchIndex
    access = Access()
    contents = None  # ContentSearch
    thumbs = None  # Thumbnails
    prober = None  # Prober
    places = None  # Places
    office = Office()  # Word and Excel, converted on request
    MAX_BODY = 16 * 1024

    # -- plumbing --------------------------------------------------------

    def log_message(self, format, *args):
        if self.server.verbose:
            sys.stderr.write("%s %s\n" % (self.address_string(), format % args))

    def send_bytes(self, body: bytes, kind: str, status=HTTPStatus.OK, headers=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, data, status=HTTPStatus.OK) -> None:
        body = json.dumps(data, separators=(",", ":")).encode()
        self.send_bytes(body, "application/json", status, {"Cache-Control": "no-store"})

    def send_text(self, status, message: str) -> None:
        self.send_bytes(message.encode() + b"\n", "text/plain; charset=utf-8", status)

    def not_found(self) -> None:
        self.send_text(HTTPStatus.NOT_FOUND, "Not found")

    def redirect(self, location: str) -> None:
        self.send_bytes(b"", "text/plain", HTTPStatus.FOUND, {"Location": location})

    def end_headers(self) -> None:
        # Headers decided before the response was chosen, e.g. a session cookie.
        for key, value in getattr(self, "pending", ()):
            self.send_header(key, value)
        self.pending = []
        super().end_headers()

    # -- routing ---------------------------------------------------------

    def do_GET(self):
        self.pending = []
        self.user = None
        self.login = None
        try:
            self.route()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # the browser moved on, e.g. seeking a video

    do_HEAD = do_GET
    def do_POST(self):
        # The one write: favorites, tags and recent files, kept outside the
        # served folder. route() refuses POST anywhere else.
        self.body_read = False
        self.do_GET()
        if not self.body_read:
            self.close_connection = True  # an unread body would garble the next request

    def route(self) -> None:
        # Collapse leading slashes first: urlsplit reads //host/x as a netloc.
        url = urlsplit("/" + self.path.lstrip("/"))
        path = unquote(url.path, errors="surrogateescape")
        query = parse_qs(url.query)

        if path == PREFIX + "logout":
            self.pending.append(("Set-Cookie", self.access.logout_cookie()))
            return self.redirect("/")
        navigating = self.headers.get("Sec-Fetch-Mode") == "navigate" or (
            "text/html" in self.headers.get("Accept", "") and not path.startswith(PREFIX))
        decision = self.access.decide(self.headers, url.path, query, navigating)
        if not decision.allowed:
            return self.refuse(decision, path, navigating)
        self.user = decision.user
        self.login = decision.login

        if self.command == "POST":
            if path != PREFIX + "api/places":
                return self.send_text(HTTPStatus.NOT_IMPLEMENTED, "shelf is read-only")
            return self.change_places()
        if decision.cookie:
            self.pending.append(("Set-Cookie", decision.cookie))
        if decision.clean_url is not None:
            # Signed in from a ?token= link: drop the token from the address bar.
            return self.redirect(decision.clean_url)

        if path.startswith(PREFIX + "api/"):
            return self.api(path[len(PREFIX) + 4 :], query)
        if path.startswith(PREFIX + "static/"):
            return self.static(path[len(PREFIX) + 7 :])

        in_frame = self.headers.get("Sec-Fetch-Dest") == "iframe"
        if path == "/" and not in_frame:
            return self.shell()
        try:
            real = self.root.resolve(path)
        except Blocked:
            return self.not_found()
        if os.path.isdir(real):
            return self.directory(real, path, in_frame)
        if os.path.isfile(real):
            return self.send_file(real)
        self.not_found()

    def refuse(self, decision, path: str, navigating: bool) -> None:
        if self.access.mode == "tailscale":
            status = HTTPStatus.FORBIDDEN
            if decision.reason == "no-identity":
                why = ("This request carries no Tailscale identity. Open shelf through its "
                       "<code>tailscale serve</code> address from a device signed in as a person, "
                       "not a tagged device.")
            else:
                why = "You're signed in to Tailscale as %s, which this server doesn't allow." % (
                    html_escape(decision.user or "unknown"))
        else:
            status = HTTPStatus.UNAUTHORIZED
            why = None
        if path.startswith(PREFIX + "api/") or not navigating:
            return self.send_json({"error": decision.reason}, status)
        if why is None:
            error = '<p class="err">That token doesn\'t match.</p>' if decision.reason == "bad-token" else ""
            body = LOGIN_PAGE.replace("{message}", error)
        else:
            body = DENIED_PAGE.replace("{message}", why)
        self.send_bytes(body.encode(), "text/html; charset=utf-8", status,
                        {"Content-Security-Policy": PAGE_CSP, "Cache-Control": "no-store"})

    def shell(self) -> None:
        body = self.asset("index.html")
        self.send_bytes(
            body,
            "text/html; charset=utf-8",
            headers={"Cache-Control": "no-cache", "Content-Security-Policy": SHELL_CSP},
        )

    def directory(self, real: str, path: str, in_frame: bool) -> None:
        rel = path.strip("/")
        link = "/" + quote(rel, errors="surrogateescape") if rel else ""
        if not in_frame:
            return self.redirect("/#" + link + "/")
        # A link followed inside a rendered HTML page: behave like a web server.
        if not path.endswith("/"):
            return self.redirect(link + "/")
        for name in ("index.html", "index.htm"):
            page = os.path.join(real, name)
            if os.path.isfile(page):
                return self.send_file(page)
        self.send_bytes(FRAME_FOLDER_PAGE, "text/html; charset=utf-8")

    def asset(self, name: str) -> bytes:
        # pkgutil reads through zipimport too, which keeps the .pyz build working.
        return pkgutil.get_data(__package__, "static/" + name)

    def static(self, name: str) -> None:
        if not re.fullmatch(r"[\w-]+(/[\w-]+)*(\.[\w-]+)+", name):
            return self.not_found()
        try:
            body = self.asset(name)
        except (OSError, KeyError):
            return self.not_found()
        etag = '"%s"' % hashlib.sha1(body).hexdigest()[:16]
        if self.headers.get("If-None-Match") == etag:
            return self.send_bytes(b"", "text/plain", HTTPStatus.NOT_MODIFIED, {"ETag": etag})
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        self.send_bytes(body, content_type(name), headers=headers)

    # -- API -------------------------------------------------------------

    def api(self, name: str, query: dict) -> None:
        arg = query.get("path", [""])[0]
        if name == "config":
            return self.send_json(
                {
                    "version": __version__,
                    "root": self.root.real,
                    "name": os.path.basename(self.root.real) or self.root.real,
                    "host": socket.gethostname(),
                    "hidden": self.root.show_hidden,
                    "access": {"mode": self.access.mode, "user": self.user},
                    "features": {
                        "thumbnails": bool(self.thumbs and self.thumbs.available),
                        "probe": bool(self.prober and self.prober.ffprobe),
                        "contents": self.contents.engine if self.contents else None,
                    },
                    **self.index_status(),
                }
            )
        if name == "search":
            results = self.index.search(query.get("q", [""])[0])
            return self.send_json({"results": results, **self.index_status()})
        if name == "grep":
            if not self.contents:
                return self.not_found()
            self.index.refresh()
            return self.send_json(self.contents.search(query.get("q", [""])[0]))
        if name == "places":
            if not self.places:
                return self.not_found()
            return self.send_json(self.places.view(self.login))
        if name not in ("list", "stat", "thumb", "probe", "office", "office-part"):
            return self.not_found()
        try:
            real = self.root.resolve(arg)
            info = os.stat(real)
        except (Blocked, OSError):
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        is_dir = os.path.isdir(real)
        if name == "thumb":
            return self.thumbnail(real, query)
        if name in ("office", "office-part"):
            return self.office_file(name, real, info, query)
        if name == "probe":
            facts = self.prober.probe(real) if self.prober and not is_dir else None
            return self.send_json(facts or {"error": "unavailable"}, HTTPStatus.OK if facts else HTTPStatus.NOT_FOUND)
        if name == "stat":
            return self.send_json(
                {
                    "type": "dir" if is_dir else "file",
                    "size": info.st_size,
                    "mtime": info.st_mtime,
                }
            )
        if not is_dir:
            return self.send_json({"error": "not a folder"}, HTTPStatus.BAD_REQUEST)
        try:
            self.send_json({"entries": self.list_dir(real)})
        except OSError as error:
            self.send_json({"error": error.strerror or "unreadable"}, HTTPStatus.FORBIDDEN)

    def thumbnail(self, real: str, query: dict) -> None:
        made = self.thumbs.get(real) if self.thumbs and os.path.isfile(real) else None
        if not made:
            return self.send_json({"error": "no thumbnail"}, HTTPStatus.NOT_FOUND)
        source, original = made
        # The URL carries the file's mtime (?v=), so a cached copy can't go stale.
        cache = "private, max-age=31536000, immutable" if "v" in query else "no-cache"
        if original:
            return self.send_file(source, cache)
        self.send_file(source, cache, kind="image/jpeg")

    def office_file(self, name: str, real: str, info, query: dict) -> None:
        if not os.path.isfile(real):
            return self.send_json({"error": "not a file"}, HTTPStatus.BAD_REQUEST)
        try:
            if name == "office":
                sheet = query.get("sheet", [None])[0]
                return self.send_json(self.office.read(real, info.st_mtime, info.st_size, sheet))
            data, kind = self.office.image(real, query.get("part", [""])[0])
        except OfficeError as error:
            status = HTTPStatus.NOT_FOUND if name == "office-part" else HTTPStatus.UNPROCESSABLE_ENTITY
            return self.send_json({"error": str(error)}, status)
        # An image inside a Word file. The URL carries the file's mtime (?v=).
        cache = "private, max-age=31536000, immutable" if "v" in query else "no-cache"
        self.send_bytes(data, kind, headers={"Cache-Control": cache,
                                             "Content-Security-Policy": "default-src 'none'; sandbox"})

    def change_places(self) -> None:
        if not self.places:
            return self.not_found()
        # Cross-site requests can't set a custom header or a JSON content type
        # without a CORS preflight, which shelf never grants; Sec-Fetch-Site
        # catches the rest in current browsers.
        site = self.headers.get("Sec-Fetch-Site")
        if (self.headers.get("X-Shelf-Request") != "1"
                or "application/json" not in self.headers.get("Content-Type", "")
                or (site is not None and site not in ("same-origin", "none"))):
            return self.send_json({"error": "refused"}, HTTPStatus.FORBIDDEN)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > self.MAX_BODY:
            self.close_connection = True
            return self.send_json({"error": "too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            raw = self.rfile.read(length)
            self.body_read = True
            change = json.loads(raw or b"{}")
            if not isinstance(change, dict):
                raise ValueError
        except ValueError:
            return self.send_json({"error": "bad request"}, HTTPStatus.BAD_REQUEST)
        try:
            view = self.places.apply(self.login, change)
        except PlaceError as error:
            return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        self.send_json(view)

    def index_status(self) -> dict:
        self.index.refresh()
        return {
            "indexed": len(self.index.paths),
            "indexing": self.index.building,
            "truncated": self.index.truncated,
        }

    def list_dir(self, real: str) -> list:
        entries = []
        with os.scandir(real) as scan:
            for entry in scan:
                name = entry.name
                if name.startswith(".") and not self.root.show_hidden:
                    continue
                if not is_utf8(name):  # cannot round-trip through a URL as text
                    continue
                try:
                    info = entry.stat()
                    if entry.is_symlink() and not self.root.allowed_target(
                        os.path.realpath(entry.path)
                    ):
                        continue
                    is_dir = entry.is_dir()
                except OSError:
                    continue  # dangling symlink
                entries.append(
                    {
                        "name": name,
                        "dir": is_dir,
                        "size": info.st_size,
                        "mtime": info.st_mtime,
                    }
                )
        entries.sort(key=lambda e: (not e["dir"], natural_key(e["name"])))
        return entries

    # -- files -----------------------------------------------------------

    def send_file(self, real: str, cache: str = "no-cache", kind: str = None) -> None:
        try:
            handle = open(real, "rb")
        except OSError:
            return self.send_text(HTTPStatus.FORBIDDEN, "Cannot read this file")
        with handle:
            info = os.fstat(handle.fileno())
            size = info.st_size
            etag = '"%x-%x"' % (info.st_mtime_ns, size)
            headers = {
                "Accept-Ranges": "bytes",
                "ETag": etag,
                "Last-Modified": email.utils.formatdate(info.st_mtime, usegmt=True),
                "Cache-Control": cache,  # revalidate by default: these files change under you
                "X-Content-Type-Options": "nosniff",
            }
            if self.headers.get("If-None-Match") == etag:
                return self.send_bytes(b"", "text/plain", HTTPStatus.NOT_MODIFIED, headers)

            status, start, length = HTTPStatus.OK, 0, size
            wanted = self.headers.get("Range")
            if_range = self.headers.get("If-Range")
            if wanted and (if_range is None or if_range == etag):
                span = parse_range(wanted, size)
                if span == "invalid":
                    headers["Content-Range"] = "bytes */%d" % size
                    return self.send_bytes(
                        b"", "text/plain", HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, headers
                    )
                if span:
                    start, end = span
                    status, length = HTTPStatus.PARTIAL_CONTENT, end - start + 1
                    headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)

            self.send_response(status)
            self.send_header("Content-Type", kind or content_type(real))
            self.send_header("Content-Length", str(length))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command == "HEAD":
                return
            handle.seek(start)
            remaining = length
            while remaining:
                block = handle.read(min(CHUNK, remaining))
                if not block:
                    # Truncated while sending: closing is the only honest signal.
                    self.close_connection = True
                    return
                self.wfile.write(block)
                remaining -= len(block)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    verbose = False

    def handle_error(self, request, client_address):
        # Browsers drop idle keep-alive connections all the time; that's not
        # worth a traceback in the terminal or the journal.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError, socket.timeout)):
            return
        super().handle_error(request, client_address)


def bind(handler, host: str, port: int, fixed: bool) -> Server:
    """Bind, walking to the next free port unless the user chose one."""
    for candidate in range(port, port + (1 if fixed else 50)):
        try:
            return Server((host, candidate), handler)
        except OSError as error:
            if fixed:
                sys.exit("shelf: cannot bind %s:%d: %s" % (host, candidate, error.strerror))
    sys.exit("shelf: no free port found from %d" % port)
