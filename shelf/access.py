"""Who may use the server.

Three modes:

- open: anyone who can reach the port. The default, as with http.server.
- tailscale: only named Tailscale users. Shelf listens on loopback behind
  `tailscale serve`, which strips any identity headers a client sends and adds
  the real Tailscale-User-Login. This is the recommended mode.
- token: anyone holding a secret token. The token arrives once in the URL, then
  lives in a cookie. Weaker: it's a shared secret, and plain HTTP exposes it to
  anyone who can watch the network.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import ipaddress
import os
import secrets
from contextlib import suppress
from dataclasses import dataclass
from email.header import decode_header
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlencode

from .storage import config_dir, write_private

IDENTITY_HEADER = "Tailscale-User-Login"
NAME_HEADER = "Tailscale-User-Name"
COOKIE_AGE = 365 * 24 * 3600


def default_token_path() -> str:
    return os.path.join(config_dir(), "token")


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def decode_rfc2047(value: str) -> str:
    """Tailscale may send non-ASCII names as =?utf-8?q?...?=."""
    try:
        parts = decode_header(value)
    except (ValueError, LookupError):
        return value
    return "".join(
        part.decode(charset or "utf-8", "replace") if isinstance(part, bytes) else part
        for part, charset in parts
    )


class TokenStore:
    """The token file, re-read when it changes so rotation needs no restart."""

    def __init__(self, path: str | None = None):
        self.env = os.environ.get("SHELF_TOKEN") or None
        self.path = path or default_token_path()
        self._seen = None
        self._token = None

    def describe(self) -> str:
        return "the SHELF_TOKEN environment variable" if self.env else self.path

    def ensure(self) -> str:
        """Return the token, creating the file on first use."""
        if self.env:
            return self.env
        if not os.path.exists(self.path):
            return self.rotate()
        return self.current()

    def rotate(self) -> str:
        if self.env:
            raise SystemExit("shelf: the token comes from SHELF_TOKEN; change it there")
        token = secrets.token_urlsafe(24)
        write_private(self.path, token + "\n")
        return token

    def current(self) -> str | None:
        if self.env:
            return self.env
        try:
            info = os.stat(self.path)
        except OSError:
            return None
        stamp = (info.st_mtime_ns, info.st_size)
        if stamp != self._seen:
            with open(self.path) as handle:
                self._token = handle.read().strip() or None
            self._seen = stamp
        return self._token


@dataclass
class Decision:
    """The answer to "may this request go ahead?", and what to send with it."""

    allowed: bool
    user: str | None = None  # display name, shown in the app
    reason: str = ""  # why not, when refused
    login: str | None = None  # Tailscale login, which keys per-person state
    cookie: str | None = None  # a Set-Cookie value to send
    clean_url: str | None = None  # redirect here to drop ?token= from the address bar


class Access:
    """The access mode in force, and the check every request goes through."""

    def __init__(
        self, mode: str = "open", port: int = 0, tokens: TokenStore | None = None, users=()
    ):
        self.mode = mode
        self.port = port
        self.tokens = tokens
        self.users = [user.lower() for user in users]

    # -- token helpers ---------------------------------------------------

    @property
    def cookie_name(self) -> str:
        # Cookies are shared by every port on a host, so name ours by port.
        return f"shelf_{self.port}"

    def session_value(self, token: str) -> str:
        # The cookie holds a derivative, so the raw token never sits in it.
        return hmac.new(token.encode(), b"shelf-session-v1", hashlib.sha256).hexdigest()

    def session_cookie(self, token: str) -> str:
        value = self.session_value(token)
        return f"{self.cookie_name}={value}; Path=/; Max-Age={COOKIE_AGE}; HttpOnly; SameSite=Lax"

    def logout_cookie(self) -> str:
        return f"{self.cookie_name}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"

    def user_allowed(self, login: str) -> bool:
        login = login.lower()
        return any(fnmatch.fnmatchcase(login, pattern) for pattern in self.users)

    # -- the check -------------------------------------------------------

    def decide(self, headers, raw_path: str, query: dict, navigating: bool) -> Decision:
        """Check a request. raw_path is still percent-encoded, for use in redirects."""
        if self.mode == "open":
            return Decision(True)
        if self.mode == "tailscale":
            return self._tailscale(headers)
        return self._token(headers, raw_path, query, navigating)

    def _tailscale(self, headers) -> Decision:
        login = headers.get(IDENTITY_HEADER)
        if not login:
            return Decision(False, reason="no-identity")
        login = decode_rfc2047(login)
        if not self.user_allowed(login):
            return Decision(False, user=login, reason="not-allowed")
        name = headers.get(NAME_HEADER)
        return Decision(True, user=decode_rfc2047(name) if name else login, login=login.lower())

    def _token(self, headers, raw_path: str, query: dict, navigating: bool) -> Decision:
        token = self.tokens.current()
        if not token:
            return Decision(False, reason="no-token-configured")
        expected = self.session_value(token)

        offered = query.get("token", [None])[0]
        if offered is not None:
            if not hmac.compare_digest(offered.encode(), token.encode()):
                return Decision(False, reason="bad-token")
            decision = Decision(True, cookie=self.session_cookie(token))
            if navigating:
                rest = {key: values for key, values in query.items() if key != "token"}
                decision.clean_url = raw_path + ("?" + urlencode(rest, doseq=True) if rest else "")
            return decision

        auth = headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            if hmac.compare_digest(auth[7:].strip().encode(), token.encode()):
                return Decision(True)
            return Decision(False, reason="bad-token")

        cookies = SimpleCookie()
        with suppress(CookieError):
            cookies.load(headers.get("Cookie", ""))
        morsel = cookies.get(self.cookie_name)
        if morsel and hmac.compare_digest(morsel.value.encode(), expected.encode()):
            return Decision(True)
        return Decision(False, reason="no-session")


# Filled in with .replace("{message}", ...) rather than %-formatting, because the CSS has % signs.
LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>shelf · sign in</title>
<style>
:root{--bg:#fff;--text:#1e2329;--muted:#5d6670;--line:rgba(30,35,41,.16);--accent:#0e7c86;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#15171a;--text:#e3e6ea;--muted:#9aa3ad;--line:rgba(227,230,234,.14);--accent:#2a8f99;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;padding:16px}
main{width:min(380px,100%)}h1{font-size:22px;margin:0 0 6px}p{color:var(--muted);margin:0 0 18px}
input{width:100%;height:38px;padding:0 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--text);font:inherit}
input:focus{outline:2px solid var(--accent);outline-offset:-1px}button{margin-top:10px;width:100%;height:38px;border:0;border-radius:6px;background:var(--accent);color:#fff;font:inherit;cursor:pointer}
.err{color:#e5484d;margin:-6px 0 14px}
</style></head><body><main>
<h1>shelf</h1><p>This server needs an access token. Paste it here, or open the link the server printed.</p>
{message}<form method="get" action="/"><input name="token" type="password" autocomplete="current-password" placeholder="Access token" aria-label="Access token" autofocus required><button>Open</button></form>
</main></body></html>"""

DENIED_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>shelf · no access</title>
<style>
:root{--bg:#fff;--text:#1e2329;--muted:#5d6670;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#15171a;--text:#e3e6ea;--muted:#9aa3ad;color-scheme:dark}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;padding:16px}
main{width:min(440px,100%)}h1{font-size:22px;margin:0 0 6px}p{color:var(--muted)}
</style></head><body><main><h1>No access</h1><p>{message}</p></main></body></html>"""

PAGE_CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
