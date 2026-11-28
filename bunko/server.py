"""The HTTP server.

Files stay at their natural URLs (/a/b.png), as with `python -m http.server`,
so curl, wget, and links inside served HTML keep working. The app lives at `/`
and routes with the URL hash (/#/a/b.md). Its assets and API sit under
/__bunko/.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import mimetypes
import os
import pkgutil
import re
import socket
import stat
import sys
from html import escape as html_escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__
from .access import DENIED_PAGE, LOGIN_PAGE, PAGE_CSP, Access
from .index import SearchIndex
from .office import Office, OfficeError
from .paths import Blocked, Root, natural_key
from .places import PlaceError

PREFIX = "/__bunko/"
DEFAULT_PORT = 8000
CHUNK = 256 * 1024
MAX_BODY = 16 * 1024
IMMUTABLE = "private, max-age=31536000, immutable"

# Types mimetypes misses or guesses badly. Other text still renders, because the
# app sniffs content rather than trusting the type.
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
    ".mov": "video/mp4",  # Chrome refuses video/quicktime but plays most .mov files
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
FRAME_FOLDER_PAGE = b"<!doctype html><title>bunko:folder</title>"


def content_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    kind = MIME_OVERRIDES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
    if kind.startswith("text/") or kind in ("application/json", "application/javascript"):
        kind += "; charset=utf-8"
    return kind


def parse_range(header: str, size: int):
    """(start, end) inclusive, None to ignore the header, or "invalid".

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


# API endpoints under /__bunko/api/, by name, and the Handler methods that answer them.
ENDPOINTS = {
    "config": "api_config",
    "search": "api_search",
    "grep": "api_grep",
    "places": "api_places",
}
# These take ?path= and receive the resolved path and its stat result.
PATH_ENDPOINTS = {
    "list": "api_list",
    "stat": "api_stat",
    "thumb": "api_thumb",
    "probe": "api_probe",
    "office": "api_office",
    "office-part": "api_office_part",
}


def _arg(query: dict, name: str, default=""):
    return query.get(name, [default])[0]


def _cache_control(query: dict) -> str:
    """URLs that carry the file's mtime (?v=) can be cached for good."""
    return IMMUTABLE if "v" in query else "no-cache"


class Handler(BaseHTTPRequestHandler):
    """One request. The services it uses are class attributes; see `make_handler`."""

    protocol_version = "HTTP/1.1"
    server_version = "bunko/" + __version__
    timeout = 120

    root: Root
    index: SearchIndex
    access = Access()
    contents = None  # ContentSearch
    thumbs = None  # Thumbnails
    prober = None  # Prober
    places = None  # Places
    office = None  # Office

    # -- responses ---------------------------------------------------------

    def log_message(self, format, *args):
        if self.server.verbose:
            sys.stderr.write(f"{self.address_string()} {format % args}\n")

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

    def send_error_json(self, message: str, status: HTTPStatus) -> None:
        self.send_json({"error": message}, status)

    def send_text(self, status, message: str) -> None:
        self.send_bytes(message.encode() + b"\n", "text/plain; charset=utf-8", status)

    def not_found(self) -> None:
        self.send_text(HTTPStatus.NOT_FOUND, "Not found")

    def redirect(self, location: str) -> None:
        self.send_bytes(b"", "text/plain", HTTPStatus.FOUND, {"Location": location})

    def end_headers(self) -> None:
        # Headers decided before the response was chosen, such as a session cookie.
        for key, value in getattr(self, "pending", ()):
            self.send_header(key, value)
        self.pending = []
        super().end_headers()

    # -- routing -----------------------------------------------------------

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
        self.body_read = False
        self.do_GET()
        if not self.body_read:
            self.close_connection = True  # an unread body would garble the next request

    def route(self) -> None:
        # Collapse leading slashes first: urlsplit reads //host/x as a host name.
        url = urlsplit("/" + self.path.lstrip("/"))
        path = unquote(url.path, errors="surrogateescape")
        query = parse_qs(url.query)

        if path == PREFIX + "logout":
            self.pending.append(("Set-Cookie", self.access.logout_cookie()))
            return self.redirect("/")
        navigating = self.headers.get("Sec-Fetch-Mode") == "navigate" or (
            "text/html" in self.headers.get("Accept", "") and not path.startswith(PREFIX)
        )
        decision = self.access.decide(self.headers, url.path, query, navigating)
        if not decision.allowed:
            return self.refuse(decision, path, navigating)
        self.user = decision.user
        self.login = decision.login

        if self.command == "POST":
            if path != PREFIX + "api/places":
                return self.send_text(HTTPStatus.NOT_IMPLEMENTED, "bunko is read-only")
            return self.change_places()
        if decision.cookie:
            self.pending.append(("Set-Cookie", decision.cookie))
        if decision.clean_url is not None:
            return self.redirect(decision.clean_url)

        if path.startswith(PREFIX + "api/"):
            return self.api(path[len(PREFIX + "api/") :], query)
        if path.startswith(PREFIX + "static/"):
            return self.static(path[len(PREFIX + "static/") :])

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
            return self.send_file(
                real, kind=content_type(path)
            )  # by the requested name: a symlink's target may have none
        return self.not_found()

    def refuse(self, decision, path: str, navigating: bool) -> None:
        status = (
            HTTPStatus.FORBIDDEN if self.access.mode == "tailscale" else HTTPStatus.UNAUTHORIZED
        )
        if path.startswith(PREFIX + "api/") or not navigating:
            return self.send_error_json(decision.reason, status)
        if self.access.mode != "tailscale":
            wrong = decision.reason == "bad-token"
            message = '<p class="err">That token doesn\'t match.</p>' if wrong else ""
            body = LOGIN_PAGE.replace("{message}", message)
        elif decision.reason == "no-identity":
            body = DENIED_PAGE.replace(
                "{message}",
                "This request carries no Tailscale identity. Open Bunko through its "
                "<code>tailscale serve</code> address from a device signed in as a person, "
                "not a tagged device.",
            )
        else:
            user = html_escape(decision.user or "unknown")
            body = DENIED_PAGE.replace(
                "{message}",
                f"You're signed in to Tailscale as {user}, which this server doesn't allow.",
            )
        headers = {"Content-Security-Policy": PAGE_CSP, "Cache-Control": "no-store"}
        return self.send_bytes(body.encode(), "text/html; charset=utf-8", status, headers)

    def shell(self) -> None:
        headers = {"Cache-Control": "no-cache", "Content-Security-Policy": SHELL_CSP}
        self.send_bytes(self.asset("index.html"), "text/html; charset=utf-8", headers=headers)

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
        return self.send_bytes(FRAME_FOLDER_PAGE, "text/html; charset=utf-8")

    @staticmethod
    def asset(name: str) -> bytes:
        # pkgutil also reads from a zip, which keeps the .pyz build working.
        return pkgutil.get_data(__package__, "static/" + name)

    def static(self, name: str) -> None:
        if not re.fullmatch(r"[\w-]+(/[\w-]+)*(\.[\w-]+)+", name):
            return self.not_found()
        try:
            body = self.asset(name)
        except (OSError, KeyError):
            return self.not_found()
        etag = f'"{hashlib.sha1(body).hexdigest()[:16]}"'
        if self.headers.get("If-None-Match") == etag:
            return self.send_bytes(b"", "text/plain", HTTPStatus.NOT_MODIFIED, {"ETag": etag})
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        return self.send_bytes(body, content_type(name), headers=headers)

    # -- API ---------------------------------------------------------------

    def api(self, name: str, query: dict) -> None:
        if name in ENDPOINTS:
            return getattr(self, ENDPOINTS[name])(query)
        if name not in PATH_ENDPOINTS:
            return self.not_found()
        try:
            real = self.root.resolve(_arg(query, "path"))
            info = os.stat(real)
        except (Blocked, OSError):
            return self.send_error_json("not found", HTTPStatus.NOT_FOUND)
        return getattr(self, PATH_ENDPOINTS[name])(real, info, query)

    def api_config(self, query: dict) -> None:
        self.send_json(
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
                **self.index.status(),
            }
        )

    def api_search(self, query: dict) -> None:
        results = self.index.search(_arg(query, "q"))
        self.send_json({"results": results, **self.index.status()})

    def api_grep(self, query: dict) -> None:
        if not self.contents:
            return self.not_found()
        self.index.refresh()
        return self.send_json(self.contents.search(_arg(query, "q")))

    def api_places(self, query: dict) -> None:
        if not self.places:
            return self.not_found()
        return self.send_json(self.places.view(self.login))

    def api_stat(self, real: str, info, query: dict) -> None:
        kind = "dir" if stat.S_ISDIR(info.st_mode) else "file"
        self.send_json({"type": kind, "size": info.st_size, "mtime": info.st_mtime})

    def api_list(self, real: str, info, query: dict) -> None:
        if not stat.S_ISDIR(info.st_mode):
            return self.send_error_json("not a folder", HTTPStatus.BAD_REQUEST)
        try:
            entries = self.list_dir(real)
        except OSError as error:
            return self.send_error_json(error.strerror or "unreadable", HTTPStatus.FORBIDDEN)
        return self.send_json({"entries": entries})

    def api_thumb(self, real: str, info, query: dict) -> None:
        made = self.thumbs.get(real) if self.thumbs and stat.S_ISREG(info.st_mode) else None
        if not made:
            return self.send_error_json("no thumbnail", HTTPStatus.NOT_FOUND)
        source, original = made
        return self.send_file(source, _cache_control(query), None if original else "image/jpeg")

    def api_probe(self, real: str, info, query: dict) -> None:
        facts = None
        if self.prober and stat.S_ISREG(info.st_mode):
            facts = self.prober.probe(real)
        if not facts:
            return self.send_error_json("unavailable", HTTPStatus.NOT_FOUND)
        return self.send_json(facts)

    def api_office(self, real: str, info, query: dict) -> None:
        if not stat.S_ISREG(info.st_mode):
            return self.send_error_json("not a file", HTTPStatus.BAD_REQUEST)
        sheet = _arg(query, "sheet", None)
        try:
            result = self.office.read(real, info.st_mtime, info.st_size, sheet)
        except OfficeError as error:
            return self.send_error_json(str(error), HTTPStatus.UNPROCESSABLE_ENTITY)
        return self.send_json(result)

    def api_office_part(self, real: str, info, query: dict) -> None:
        """An image embedded in a Word file."""
        if not stat.S_ISREG(info.st_mode):
            return self.send_error_json("not a file", HTTPStatus.BAD_REQUEST)
        try:
            data, kind = self.office.image(real, _arg(query, "part"))
        except OfficeError as error:
            return self.send_error_json(str(error), HTTPStatus.NOT_FOUND)
        headers = {
            "Cache-Control": _cache_control(query),
            "Content-Security-Policy": "default-src 'none'; sandbox",
        }
        return self.send_bytes(data, kind, headers=headers)

    def change_places(self) -> None:
        """The one write: recent files, favorites, and tags, kept outside the served folder."""
        if not self.places:
            return self.not_found()
        # Cross-site requests can't set a custom header or a JSON content type
        # without a CORS preflight, which bunko never grants. Sec-Fetch-Site
        # catches the rest in current browsers.
        site = self.headers.get("Sec-Fetch-Site")
        if (
            self.headers.get("X-Bunko-Request") != "1"
            or "application/json" not in self.headers.get("Content-Type", "")
            or (site is not None and site not in ("same-origin", "none"))
        ):
            return self.send_error_json("refused", HTTPStatus.FORBIDDEN)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            return self.send_error_json("too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            raw = self.rfile.read(length)
            self.body_read = True
            change = json.loads(raw or b"{}")
            if not isinstance(change, dict):
                raise ValueError("not an object")
        except ValueError:
            return self.send_error_json("bad request", HTTPStatus.BAD_REQUEST)
        try:
            view = self.places.apply(self.login, change)
        except PlaceError as error:
            return self.send_error_json(str(error), HTTPStatus.BAD_REQUEST)
        return self.send_json(view)

    def list_dir(self, real: str) -> list:
        entries = []
        with os.scandir(real) as scan:
            for entry in scan:
                if not self.root.visible(entry.name):
                    continue
                try:
                    info = entry.stat()
                    if entry.is_symlink() and not self.root.allowed_target(
                        os.path.realpath(entry.path)
                    ):
                        continue
                    is_dir = entry.is_dir()
                except OSError:
                    continue  # a dangling symlink
                entries.append(
                    {
                        "name": entry.name,
                        "dir": is_dir,
                        "size": info.st_size,
                        "mtime": info.st_mtime,
                    }
                )
        entries.sort(key=lambda entry: (not entry["dir"], natural_key(entry["name"])))
        return entries

    # -- files -------------------------------------------------------------

    def send_file(self, real: str, cache: str = "no-cache", kind: str | None = None) -> None:
        """Send a file, honoring Range, If-Range, and If-None-Match."""
        try:
            handle = open(real, "rb")  # noqa: SIM115 -- closed by the `with` below
        except OSError:
            return self.send_text(HTTPStatus.FORBIDDEN, "Cannot read this file")
        with handle:
            info = os.fstat(handle.fileno())
            size = info.st_size
            etag = f'"{info.st_mtime_ns:x}-{size:x}"'
            headers = {
                "Accept-Ranges": "bytes",
                "ETag": etag,
                "Last-Modified": email.utils.formatdate(info.st_mtime, usegmt=True),
                "Cache-Control": cache,
            }
            if self.headers.get("If-None-Match") == etag:
                return self.send_bytes(b"", "text/plain", HTTPStatus.NOT_MODIFIED, headers)

            status, start, length = HTTPStatus.OK, 0, size
            wanted = self.headers.get("Range")
            if_range = self.headers.get("If-Range")
            if wanted and (if_range is None or if_range == etag):
                span = parse_range(wanted, size)
                if span == "invalid":
                    headers["Content-Range"] = f"bytes */{size}"
                    status = HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE
                    return self.send_bytes(b"", "text/plain", status, headers)
                if span:
                    start, end = span
                    status, length = HTTPStatus.PARTIAL_CONTENT, end - start + 1
                    headers["Content-Range"] = f"bytes {start}-{end}/{size}"

            self.send_response(status)
            self.send_header("Content-Type", kind or content_type(real))
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self._copy(handle, start, length)
        return None

    def _copy(self, handle, start: int, length: int) -> None:
        handle.seek(start)
        while length:
            block = handle.read(min(CHUNK, length))
            if not block:
                # The file shrank while sending: closing is the only honest signal.
                self.close_connection = True
                return
            self.wfile.write(block)
            length -= len(block)


def make_handler(root: Root, index: SearchIndex, **services) -> type:
    """A Handler subclass bound to one served folder and its services."""
    services.setdefault("office", Office())
    return type("BoundHandler", (Handler,), {"root": root, "index": index, **services})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    verbose = False

    def handle_error(self, request, client_address):
        # Browsers drop idle keep-alive connections all the time; that's not
        # worth a traceback.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError, socket.timeout)):
            return
        super().handle_error(request, client_address)


def bind(handler: type, host: str, port: int, fixed: bool) -> Server:
    """Bind, walking to the next free port unless the user chose one."""
    for candidate in range(port, port + (1 if fixed else 50)):
        try:
            return Server((host, candidate), handler)
        except OSError as error:
            if fixed:
                sys.exit(f"bunko: cannot bind {host}:{candidate}: {error.strerror}")
    sys.exit(f"bunko: no free port found from {port}")
