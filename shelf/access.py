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
from email.header import decode_header
from http.cookies import SimpleCookie
from urllib.parse import urlencode

IDENTITY_HEADER = "Tailscale-User-Login"
NAME_HEADER = "Tailscale-User-Name"
COOKIE_AGE = 365 * 24 * 3600


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "shelf")


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
    except Exception:
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
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        temp = self.path + ".tmp"
        # Created 0600 from the start, never briefly world-readable.
        handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w") as out:
            out.write(token + "\n")
        os.replace(temp, self.path)
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


class Decision:
    def __init__(self, allowed: bool, user: str | None = None, reason: str = ""):
        self.allowed = allowed
        self.user = user
        self.reason = reason
        self.login: str | None = None  # Tailscale login, when known
        self.cookie: str | None = None  # Set-Cookie value to send
        self.clean_url: str | None = None  # redirect here to drop ?token= from the address bar


class Access:
    def __init__(self, mode: str = "open", port: int = 0, tokens: TokenStore | None = None, users=()):
        self.mode = mode
        self.port = port
        self.tokens = tokens
        self.users = [user.lower() for user in users]

    # -- token helpers ---------------------------------------------------

    @property
    def cookie_name(self) -> str:
        # Cookies are shared by every port on a host, so name ours by port.
        return "shelf_%d" % self.port

    def session_value(self, token: str) -> str:
        # The cookie holds a derivative, so the raw token never sits in it.
        return hmac.new(token.encode(), b"shelf-session-v1", hashlib.sha256).hexdigest()

    def session_cookie(self, token: str) -> str:
        return "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax" % (
            self.cookie_name, self.session_value(token), COOKIE_AGE)

    def logout_cookie(self) -> str:
        return "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" % self.cookie_name

    def user_allowed(self, login: str) -> bool:
        login = login.lower()
        return any(fnmatch.fnmatchcase(login, pattern) for pattern in self.users)

    # -- the check -------------------------------------------------------

    def decide(self, headers, raw_path: str, query: dict, navigating: bool) -> Decision:
        """raw_path is the still-percent-encoded request path, reused in redirects."""
        if self.mode == "open":
            return Decision(True)
        if self.mode == "tailscale":
            login = headers.get(IDENTITY_HEADER)
            if not login:
                return Decision(False, reason="no-identity")
            login = decode_rfc2047(login)
            if not self.user_allowed(login):
                return Decision(False, user=login, reason="not-allowed")
            name = headers.get(NAME_HEADER)
            decision = Decision(True, user=decode_rfc2047(name) if name else login)
            decision.login = login.lower()  # keys this person's favorites and tags
            return decision

        token = self.tokens.current()
        if not token:
            return Decision(False, reason="no-token-configured")
        expected = self.session_value(token)

        offered = query.get("token", [None])[0]
        if offered is not None:
            if not hmac.compare_digest(offered.encode(), token.encode()):
                return Decision(False, reason="bad-token")
            decision = Decision(True)
            decision.cookie = self.session_cookie(token)
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
        try:
            cookies.load(headers.get("Cookie", ""))
        except Exception:
            pass
        morsel = cookies.get(self.cookie_name)
        if morsel and hmac.compare_digest(morsel.value.encode(), expected.encode()):
            return Decision(True)
        return Decision(False, reason="no-session")


# Filled with .replace("{message}", ...): the CSS is full of % signs.
LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>shelf · sign in</title>
<style>
:root{--bg:#fff;--text:#37352f;--muted:#787774;--line:rgba(55,53,47,.16);--accent:#2383e2;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#191919;--text:rgba(255,255,255,.84);--muted:#9b9b9b;--line:rgba(255,255,255,.14);--accent:#529cca;color-scheme:dark}}
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
:root{--bg:#fff;--text:#37352f;--muted:#787774;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#191919;--text:rgba(255,255,255,.84);--muted:#9b9b9b;color-scheme:dark}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;padding:16px}
main{width:min(440px,100%)}h1{font-size:22px;margin:0 0 6px}p{color:var(--muted)}
</style></head><body><main><h1>No access</h1><p>{message}</p></main></body></html>"""

PAGE_CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
