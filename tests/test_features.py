"""Access control, thumbnails, video probing, content search and the service unit.

Run with: python3 -m unittest discover -s tests
"""

import http.client
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from shelf import server as shelf
from shelf import service
from shelf.access import Access, TokenStore, decode_rfc2047
from shelf.cli import parse_args
from shelf.contents import ContentSearch
from shelf.index import SKIP_DIRS, SearchIndex
from shelf.media import Prober, Thumbnails
from shelf.paths import Root
from shelf.places import PlaceError, Places

FFMPEG = shutil.which("ffmpeg")


def ffmpeg(*args):
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", *args], check=True)


class Running:
    """A shelf server on a free loopback port, for one test class."""

    def __init__(self, root, access=None, **parts):
        self.root = Root(str(root), False)
        self.index = SearchIndex(self.root)
        if access is not None:
            parts["access"] = access
        handler = shelf.make_handler(self.root, self.index, **parts)
        self.server = shelf.Server(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        if access is not None:
            access.port = self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.index.refresh()
        while self.index.building or not self.index.built_at:
            time.sleep(0.01)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def get(self, path, headers=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.putrequest(method, path, skip_accept_encoding=True)
        for key, value in (headers or {}).items():
            conn.putheader(key, value)
        conn.endheaders()
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body


NAV = {"Sec-Fetch-Mode": "navigate", "Accept": "text/html"}


class TokenAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(cls.tmp.name)
        (base / "root" / "sub dir").mkdir(parents=True)
        (base / "root" / "hello.txt").write_text("hello")
        (base / "root" / "sub dir" / "a%b.txt").write_text("odd")
        cls.store = TokenStore(str(base / "cfg" / "token"))
        cls.token = cls.store.ensure()
        cls.srv = Running(base / "root", Access("token", 0, cls.store))

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.tmp.cleanup()

    def cookie_for(self, token):
        return f"{self.srv.server.RequestHandlerClass.access.cookie_name}={self.srv.server.RequestHandlerClass.access.session_value(token)}"

    def test_token_file_is_private(self):
        mode = stat.S_IMODE(os.stat(self.store.path).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertGreaterEqual(len(self.token), 30)

    def test_everything_is_locked_without_a_token(self):
        for path in (
            "/",
            "/hello.txt",
            "/__shelf/api/list?path=",
            "/__shelf/static/js/app.js",
            "/sub%20dir/",
        ):
            response, body = self.srv.get(path)
            self.assertEqual(response.status, 401, path)
            self.assertNotIn(b"hello", body)

    def test_browser_gets_the_sign_in_page(self):
        response, body = self.srv.get("/", NAV)
        self.assertEqual(response.status, 401)
        self.assertIn(b'name="token"', body)
        self.assertIn("default-src 'none'", response.getheader("Content-Security-Policy"))

    def test_link_signs_in_and_cleans_the_address_bar(self):
        response, _ = self.srv.get("/?token=" + self.token, NAV)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.getheader("Location"), "/")
        cookie = response.getheader("Set-Cookie")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn(self.token, cookie)  # the cookie holds a derivative
        session = cookie.split(";")[0]
        response, body = self.srv.get("/hello.txt", {"Cookie": session})
        self.assertEqual((response.status, body), (200, b"hello"))

    def test_clean_redirect_keeps_other_params_and_encoding(self):
        path = "/" + quote("sub dir") + "/" + quote("a%b.txt")
        response, _ = self.srv.get(path + "?x=1&token=" + self.token, NAV)
        self.assertEqual(response.getheader("Location"), path + "?x=1")

    def test_wrong_token_says_so(self):
        response, body = self.srv.get("/?token=nope", NAV)
        self.assertEqual(response.status, 401)
        self.assertIn(b"doesn't match", body)

    def test_scripts_can_use_a_bearer_header_or_query(self):
        response, body = self.srv.get("/hello.txt", {"Authorization": "Bearer " + self.token})
        self.assertEqual((response.status, body), (200, b"hello"))
        response, body = self.srv.get("/hello.txt?token=" + self.token)
        self.assertEqual((response.status, body), (200, b"hello"))
        response, _ = self.srv.get("/hello.txt", {"Authorization": "Bearer wrong"})
        self.assertEqual(response.status, 401)

    def test_forged_cookie_fails(self):
        name = self.srv.server.RequestHandlerClass.access.cookie_name
        for value in (self.token, "0" * 64, ""):
            response, _ = self.srv.get("/hello.txt", {"Cookie": f"{name}={value}"})
            self.assertEqual(response.status, 401, value)

    def test_logout_clears_the_cookie(self):
        response, _ = self.srv.get("/__shelf/logout")
        self.assertEqual(response.status, 302)
        self.assertIn("Max-Age=0", response.getheader("Set-Cookie"))

    def test_rotation_takes_effect_without_restart(self):
        old_cookie = self.cookie_for(self.token)
        time.sleep(0.01)
        new = self.store.rotate()
        try:
            response, _ = self.srv.get("/hello.txt", {"Cookie": old_cookie})
            self.assertEqual(response.status, 401)
            response, _ = self.srv.get("/hello.txt", {"Cookie": self.cookie_for(new)})
            self.assertEqual(response.status, 200)
        finally:
            with open(self.store.path, "w") as out:
                out.write(self.token + "\n")

    def test_env_token_wins_and_cannot_be_rotated(self):
        with mock.patch.dict(os.environ, {"SHELF_TOKEN": "from-env"}):
            store = TokenStore(self.store.path)
            self.assertEqual(store.ensure(), "from-env")
            with self.assertRaises(SystemExit):
                store.rotate()


class TailscaleAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.tmp.name)
        (root / "hello.txt").write_text("hello")
        access = Access("tailscale", 0, users=["me@example.com", "*@team.example"])
        cls.srv = Running(root, access)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.tmp.cleanup()

    def test_allowed_users(self):
        for login in ("me@example.com", "ME@example.com", "anyone@team.example"):
            response, body = self.srv.get("/hello.txt", {"Tailscale-User-Login": login})
            self.assertEqual((response.status, body), (200, b"hello"), login)

    def test_other_users_and_missing_identity_are_refused(self):
        for headers in (
            {"Tailscale-User-Login": "someone@else.example"},
            {},
            {"Tailscale-User-Login": "me@example.com.evil"},
        ):
            response, body = self.srv.get("/hello.txt", headers)
            self.assertEqual(response.status, 403, headers)
            self.assertNotIn(b"hello", body)

    def test_refusal_page_escapes_the_login(self):
        response, body = self.srv.get(
            "/", {**NAV, "Tailscale-User-Login": "<script>x</script>@e.example"}
        )
        self.assertEqual(response.status, 403)
        self.assertNotIn(b"<script>x", body)
        self.assertIn(b"&lt;script&gt;", body)

    def test_config_reports_who_is_signed_in(self):
        _, body = self.srv.get(
            "/__shelf/api/config",
            {
                "Tailscale-User-Login": "me@example.com",
                "Tailscale-User-Name": "=?utf-8?q?Ferris_B=C3=BCller?=",
            },
        )
        self.assertEqual(json.loads(body)["access"], {"mode": "tailscale", "user": "Ferris Büller"})

    def test_rfc2047(self):
        self.assertEqual(decode_rfc2047("plain"), "plain")
        self.assertEqual(decode_rfc2047("=?utf-8?q?Ferris_B=C3=BCller?="), "Ferris Büller")


class AccessArguments(unittest.TestCase):
    def test_allow_user_needs_loopback(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            parse_args(["--allow-user", "me@example.com"])
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            parse_args(["--allow-user", "me@example.com", "-b", "100.64.0.1"])
        args = parse_args(["--allow-user", "me@example.com", "-b", "127.0.0.1"])
        self.assertEqual(args.allow_user, ["me@example.com"])
        parse_args(["--allow-user", "me@example.com", "-b", "::1"])

    def test_one_mode_at_a_time(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            parse_args(["--allow-user", "a@b.c", "-b", "127.0.0.1", "--token"])

    def test_new_token_implies_token(self):
        self.assertTrue(parse_args(["--new-token"]).token)


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class Media(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(cls.tmp.name)
        root = base / "root"
        (root / ".hidden").mkdir(parents=True)
        # Noise defeats PNG compression, so this lands well above the as-is threshold.
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=1600x1200:d=1,noise=alls=80:allf=t",
            "-frames:v",
            "1",
            str(root / "big.png"),
        )
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=32x32:d=1",
            "-frames:v",
            "1",
            str(root / "small.png"),
        )
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=320x240:r=25:d=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(root / "clip.mp4"),
        )
        ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=320x240:r=25:d=0.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(root / "short.mp4"),
        )
        (root / "corrupt.mp4").write_bytes(b"\0" * 2048)
        (root / "-i.png").write_bytes((root / "big.png").read_bytes())
        shutil.copy(root / "big.png", root / ".hidden" / "secret.png")
        cls.cache = base / "cache"
        cls.srv = Running(root, thumbs=Thumbnails(str(cls.cache)), prober=Prober())

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.tmp.cleanup()

    def thumb(self, name):
        return self.srv.get(f"/__shelf/api/thumb?path={quote(name)}&v=1")

    def test_big_image_gets_a_small_jpeg(self):
        response, body = self.thumb("big.png")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "image/jpeg")
        self.assertIn("immutable", response.getheader("Cache-Control"))
        self.assertLess(len(body), os.path.getsize(os.path.join(self.srv.root.real, "big.png")) / 4)
        self.assertTrue(any(self.cache.rglob("*.jpg")))

    def test_small_image_is_sent_as_is(self):
        response, _ = self.thumb("small.png")
        self.assertEqual((response.status, response.getheader("Content-Type")), (200, "image/png"))

    def test_video_poster_and_very_short_video(self):
        for name in ("clip.mp4", "short.mp4"):
            response, body = self.thumb(name)
            self.assertEqual(
                (response.status, response.getheader("Content-Type")), (200, "image/jpeg"), name
            )
            self.assertTrue(body.startswith(b"\xff\xd8"), name)

    def test_unreadable_video_fails_once_and_is_remembered(self):
        response, _ = self.thumb("corrupt.mp4")
        self.assertEqual(response.status, 404)
        self.assertTrue(any(self.cache.rglob("*.fail")))
        started = time.monotonic()
        self.thumb("corrupt.mp4")
        self.assertLess(time.monotonic() - started, 0.5)

    def test_name_that_looks_like_an_option(self):
        response, _ = self.thumb("-i.png")
        self.assertEqual(response.status, 200)

    def test_hidden_and_non_media(self):
        response, _ = self.thumb(".hidden/secret.png")
        self.assertEqual(response.status, 404)
        response, _ = self.thumb("nope.png")
        self.assertEqual(response.status, 404)

    def test_probe(self):
        response, body = self.srv.get("/__shelf/api/probe?path=clip.mp4")
        facts = json.loads(body)
        self.assertEqual(
            (response.status, facts["fps"], facts["codec"], facts["width"]),
            (200, 25.0, "h264", 320),
        )
        self.assertAlmostEqual(facts["duration"], 3.0, delta=0.1)


class Contents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(cls.tmp.name)
        root = base / "root"
        secret = base / ".private"
        for folder in (root / "notes", root / ".git", root / "node_modules", secret):
            folder.mkdir(parents=True)
        (root / "notes" / "plan.md").write_text(
            "# Plan\n\nThe squeeze_b input size matters.\nAnother SQUEEZE_B line.\n"
        )
        (root / "notes" / "long.txt").write_text("x" * 5000 + " squeeze_b " + "y" * 5000 + "\n")
        (root / "notes" / "bin.dat").write_bytes(b"\0squeeze_b\0")
        (root / ".git" / "config").write_text("squeeze_b in a dotfile\n")
        (root / "node_modules" / "dep.js").write_text("squeeze_b in a dependency\n")
        (secret / "key.txt").write_text("squeeze_b PRIVATE\n")
        (root / "leak").symlink_to(secret)
        cls.root = root
        cls.srv = Running(root)
        cls.search = ContentSearch(cls.srv.root, cls.srv.index, SKIP_DIRS)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.tmp.cleanup()

    def engines(self):
        yield "python", mock.patch.object(self.search, "rg", None)
        if shutil.which("rg"):
            yield "ripgrep", mock.patch.object(self.search, "rg", shutil.which("rg"))

    def test_finds_lines_case_insensitively_with_marks(self):
        for engine, patch in self.engines():
            with patch:
                data = self.search.search("squeeze_b")
            hits = [(h["path"], h["line"]) for h in data["results"]]
            self.assertIn(("notes/plan.md", 3), hits, engine)
            self.assertIn(("notes/plan.md", 4), hits, engine)
            first = next(h for h in data["results"] if h["line"] == 3)
            start, end = first["marks"][0]
            self.assertEqual(first["text"][start:end], "squeeze_b", engine)

    def test_long_lines_are_trimmed_around_the_match(self):
        for engine, patch in self.engines():
            with patch:
                data = self.search.search("squeeze_b")
            hit = next(h for h in data["results"] if h["path"] == "notes/long.txt")
            self.assertLessEqual(len(hit["text"]), 220, engine)
            start, end = hit["marks"][0]
            self.assertEqual(hit["text"][start:end], "squeeze_b", engine)

    def test_never_leaks_hidden_binary_or_skipped_files(self):
        for engine, patch in self.engines():
            with patch:
                data = self.search.search("squeeze_b")
            paths = {h["path"] for h in data["results"]}
            self.assertEqual(paths, {"notes/plan.md", "notes/long.txt"}, engine)
            self.assertNotIn("PRIVATE", json.dumps(data))

    def test_too_short(self):
        self.assertEqual(self.search.search("s")["results"], [])


WRITE = {
    "Content-Type": "application/json",
    "X-Shelf-Request": "1",
    "Sec-Fetch-Site": "same-origin",
}


class PlacesStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        root = base / "root"
        (root / "notes").mkdir(parents=True)
        (root / ".private").mkdir()
        for name in ("a.md", "b.md", "notes/c.md", ".private/key"):
            (root / name).write_text("x")
        self.root = root
        self.state = base / "state"
        self.places = Places(Root(str(root), False), str(self.state))

    def tearDown(self):
        self.tmp.cleanup()

    def test_recent_is_newest_first_without_duplicates(self):
        for path in ("a.md", "b.md", "a.md"):
            view = self.places.apply(None, {"op": "visit", "path": path})
        self.assertEqual([r["path"] for r in view["recent"]], ["a.md", "b.md"])

    def test_recent_keeps_fifty(self):
        for i in range(60):
            (self.root / f"f{i}.txt").write_text("x")
            self.places.apply(None, {"op": "visit", "path": f"f{i}.txt"})
        self.assertEqual(len(self.places.view(None)["recent"]), 50)

    def test_favorites_and_tags(self):
        self.places.apply(None, {"op": "favorite", "path": "notes", "on": True})
        self.places.apply(None, {"op": "tag", "path": "a.md", "tag": "review"})
        view = self.places.apply(
            None, {"op": "tag", "path": "notes/c.md", "tag": "Review"}
        )  # same tag, any case
        self.assertEqual(view["favorites"], [{"path": "notes", "dir": True, "missing": False}])
        self.assertEqual([t["name"] for t in view["tags"]], ["review"])
        self.assertEqual([f["path"] for f in view["tags"][0]["files"]], ["a.md", "notes/c.md"])
        self.assertEqual(view["tagged"]["a.md"], ["review"])

    def test_favorite_nicknames(self):
        view = self.places.apply(
            None, {"op": "favorite", "path": "notes/c.md", "on": True, "name": "  Team   notes "}
        )
        self.assertEqual(
            view["favorites"][0],
            {"path": "notes/c.md", "dir": False, "missing": False, "name": "Team notes"},
        )
        view = self.places.apply(
            None, {"op": "rename-favorite", "path": "notes/c.md", "name": "Plan"}
        )
        self.assertEqual(view["favorites"][0]["name"], "Plan")
        for clearing in ("", "c.md"):  # empty, or the file name itself, means no nickname
            self.places.apply(None, {"op": "rename-favorite", "path": "notes/c.md", "name": "x"})
            view = self.places.apply(
                None, {"op": "rename-favorite", "path": "notes/c.md", "name": clearing}
            )
            self.assertNotIn("name", view["favorites"][0], clearing)

    def test_nickname_rules(self):
        self.places.apply(None, {"op": "favorite", "path": "a.md"})
        for bad in ("x" * 61, "line\x00break"):
            with self.assertRaises(PlaceError):
                self.places.apply(None, {"op": "rename-favorite", "path": "a.md", "name": bad})
        with self.assertRaises(PlaceError):
            self.places.apply(
                None, {"op": "rename-favorite", "path": "b.md", "name": "not a favorite"}
            )

    def test_unfavoriting_drops_the_nickname(self):
        self.places.apply(None, {"op": "favorite", "path": "a.md", "name": "Alpha"})
        self.places.apply(None, {"op": "favorite", "path": "a.md", "on": False})
        view = self.places.apply(None, {"op": "favorite", "path": "a.md"})
        self.assertNotIn("name", view["favorites"][0])

    def test_untagging_the_last_file_removes_the_tag(self):
        self.places.apply(None, {"op": "tag", "path": "a.md", "tag": "x"})
        view = self.places.apply(None, {"op": "untag", "path": "a.md", "tag": "x"})
        self.assertEqual(view["tags"], [])

    def test_rename_and_merge_tags(self):
        self.places.apply(None, {"op": "tag", "path": "a.md", "tag": "one"})
        self.places.apply(None, {"op": "tag", "path": "b.md", "tag": "two"})
        view = self.places.apply(None, {"op": "rename-tag", "tag": "one", "name": "first"})
        self.assertEqual(sorted(t["name"] for t in view["tags"]), ["first", "two"])
        view = self.places.apply(None, {"op": "rename-tag", "tag": "first", "name": "TWO"})
        self.assertEqual(
            [(t["name"], [f["path"] for f in t["files"]]) for t in view["tags"]],
            [("two", ["b.md", "a.md"])],
        )

    def test_hidden_missing_and_escaping_paths_are_refused(self):
        for path in (".private/key", "../x", "nope.md", "", "/"):
            for op in ("visit", "favorite", "tag"):
                with self.assertRaises(PlaceError, msg=(op, path)):
                    self.places.apply(None, {"op": op, "path": path, "tag": "t", "on": True})

    def test_bad_tag_names(self):
        for name in ("", " ", "a/b", "x" * 41, "nul\x00"):
            with self.assertRaises(PlaceError, msg=name):
                self.places.apply(None, {"op": "tag", "path": "a.md", "tag": name})
        view = self.places.apply(None, {"op": "tag", "path": "a.md", "tag": "  needs\t review "})
        self.assertEqual([t["name"] for t in view["tags"]], ["needs review"])  # whitespace tidied

    def test_people_have_separate_lists(self):
        self.places.apply("me@example.com", {"op": "favorite", "path": "a.md"})
        self.assertEqual(self.places.view("ME@example.com")["favorites"][0]["path"], "a.md")
        self.assertEqual(self.places.view("you@example.com")["favorites"], [])
        self.assertEqual(self.places.view(None)["favorites"], [])

    def test_saved_privately_and_survives_restart(self):
        self.places.apply(None, {"op": "favorite", "path": "a.md"})
        files = list(self.state.glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(stat.S_IMODE(os.stat(files[0]).st_mode), 0o600)
        again = Places(Root(str(self.root), False), str(self.state))
        self.assertEqual(again.view(None)["favorites"][0]["path"], "a.md")
        self.assertFalse(any(self.root.rglob("*.json")))  # nothing written into the served folder

    def test_deleted_files_drop_from_recent_but_stay_as_missing_favorites(self):
        self.places.apply(None, {"op": "visit", "path": "b.md"})
        self.places.apply(None, {"op": "favorite", "path": "b.md"})
        (self.root / "b.md").unlink()
        view = self.places.view(None)
        self.assertEqual(view["recent"], [])
        self.assertEqual(view["favorites"], [{"path": "b.md", "dir": False, "missing": True}])

    def test_paths_that_become_hidden_are_not_shown(self):
        self.places.data["users"]["default"] = {
            "recent": [],
            "favorites": [".private/key"],
            "tags": {"t": [".private/key"]},
        }
        view = self.places.view(None)
        self.assertEqual((view["favorites"], view["tags"][0]["files"]), ([], []))


class PlacesHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(cls.tmp.name)
        root = base / "root"
        root.mkdir()
        (root / "a.md").write_text("x")
        cls.srv = Running(root, places=Places(Root(str(root), False), str(base / "state")))
        tokens = TokenStore(str(base / "token"))
        cls.token = tokens.ensure()
        cls.locked = Running(
            root,
            Access("token", 0, tokens),
            places=Places(Root(str(root), False), str(base / "state2")),
        )

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.locked.stop()
        cls.tmp.cleanup()

    def post(self, srv, body, headers=WRITE):
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        data = json.dumps(body).encode() if not isinstance(body, bytes) else body
        conn.request("POST", "/__shelf/api/places", body=data, headers=headers)
        response = conn.getresponse()
        payload = response.read()
        conn.close()
        return response.status, payload

    def test_write_then_read(self):
        status, body = self.post(self.srv, {"op": "favorite", "path": "a.md"})
        self.assertEqual(status, 200)
        _response, body = self.srv.get("/__shelf/api/places")
        self.assertEqual(json.loads(body)["favorites"][0]["path"], "a.md")

    def test_cross_site_writes_are_refused(self):
        attempts = [
            {
                "Content-Type": "application/json",
                "Sec-Fetch-Site": "same-origin",
            },  # no custom header
            {"Content-Type": "text/plain", "X-Shelf-Request": "1"},  # a simple form-like request
            {
                "Content-Type": "application/json",
                "X-Shelf-Request": "1",
                "Sec-Fetch-Site": "cross-site",
            },
            {
                "Content-Type": "application/json",
                "X-Shelf-Request": "1",
                "Sec-Fetch-Site": "same-site",
            },
        ]
        for headers in attempts:
            status, _ = self.post(self.srv, {"op": "clear-recent"}, headers)
            self.assertEqual(status, 403, headers)

    def test_bad_bodies(self):
        self.assertEqual(self.post(self.srv, b"not json")[0], 400)
        self.assertEqual(self.post(self.srv, [1, 2])[0], 400)
        self.assertEqual(self.post(self.srv, {"op": "explode"})[0], 400)
        status, body = self.post(self.srv, {"op": "tag", "path": "a.md", "tag": "a/b"})
        self.assertEqual(status, 400)
        self.assertIn("slashes", json.loads(body)["error"])
        self.assertEqual(self.post(self.srv, b"{" + b" " * 20000 + b"}")[0], 413)

    def test_other_posts_stay_read_only(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
        conn.request("POST", "/a.md", body=b"overwrite", headers=WRITE)
        self.assertEqual(conn.getresponse().status, 501)
        conn.close()
        self.assertEqual((pathlib.Path(self.srv.root.real) / "a.md").read_text(), "x")

    def test_writes_need_access_too(self):
        status, _ = self.post(self.locked, {"op": "favorite", "path": "a.md"})
        self.assertEqual(status, 401)
        status, _ = self.post(
            self.locked,
            {"op": "favorite", "path": "a.md"},
            {**WRITE, "Authorization": "Bearer " + self.token},
        )
        self.assertEqual(status, 200)


class ServiceUnit(unittest.TestCase):
    def test_arguments_are_validated_and_made_absolute(self):
        with mock.patch("os.getcwd", return_value="/srv/docs"):
            args = service.serve_arguments(
                ["8100", ".", "-b", "127.0.0.1", "--allow-user", "me@example.com"]
            )
        self.assertEqual(
            args,
            [
                "--port",
                "8100",
                "--directory",
                "/srv/docs",
                "--bind",
                "127.0.0.1",
                "--allow-user",
                "me@example.com",
            ],
        )

    def test_bad_arguments_are_refused(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            service.serve_arguments(["--allow-user", "me@example.com"])  # not loopback

    def test_unit_quotes_and_escapes_percent(self):
        text = service.render_unit(
            "docs", ["/usr/bin/python3", "-m", "shelf", "--directory", "/data/100% done"]
        )
        self.assertIn("ExecStart=/usr/bin/python3 -m shelf --directory '/data/100%% done'", text)
        self.assertIn("Restart=on-failure", text)
        self.assertIn("WantedBy=default.target", text)

    def test_launcher_ignores_the_working_directory(self):
        with mock.patch.object(sys, "argv", ["/usr/local/bin/shelf"]):
            self.assertEqual(service.launcher()[1:], ["-I", "-u", "-m", "shelf"])
        with tempfile.NamedTemporaryFile(suffix=".pyz") as pyz, mock.patch.object(
            sys, "argv", [pyz.name]
        ):
            self.assertEqual(service.launcher()[1:], ["-I", "-u", pyz.name])

    def test_isolated_launch_ignores_a_shelf_folder_in_the_working_directory(self):
        # The bug this guards against: services start in ~, and with an editable
        # install `python -m shelf` imported a checkout at ~/shelf instead.
        with tempfile.TemporaryDirectory() as cwd:
            os.makedirs(os.path.join(cwd, "shelf"))
            with open(os.path.join(cwd, "shelf", "__init__.py"), "w") as out:
                out.write("print('DECOY')\n")
            with open(os.path.join(cwd, "shelf", "__main__.py"), "w") as out:
                out.write("")
            plain = subprocess.run(
                [sys.executable, "-m", "shelf"], cwd=cwd, capture_output=True, text=True
            )
            self.assertIn("DECOY", plain.stdout)
            isolated = subprocess.run(
                [sys.executable, "-I", "-u", "-m", "shelf", "--version"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("DECOY", isolated.stdout)

    def test_install_print_does_not_touch_systemd(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": home}
        ), mock.patch("subprocess.run") as run, mock.patch("sys.stdout") as out:
            service.main(["install", "--name", "docs", "--print", "--", "8100", "/tmp"])
        run.assert_not_called()
        written = "".join(call.args[0] for call in out.write.call_args_list)
        self.assertIn("--port 8100 --directory /tmp", written)


if __name__ == "__main__":
    unittest.main()
