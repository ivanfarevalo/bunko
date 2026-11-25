"""Run with: python3 -m unittest discover -s tests"""

import http.client
import json
import pathlib
import socket
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import quote

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from shelf import server as shelf
from shelf.cli import parse_args
from shelf.index import SearchIndex
from shelf.paths import Root, natural_key


class ServerCase(unittest.TestCase):
    hidden = False

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(cls.tmp.name)
        root = base / "root"
        outside = base / "outside"
        secret = base / ".private"
        for folder in (root / "sub" / "deep", root / ".ssh", root / "site", outside, secret):
            folder.mkdir(parents=True)
        (root / "hello.txt").write_bytes(b"0123456789")
        (root / "empty.txt").write_bytes(b"")
        (root / "a b#c?d%e.md").write_text("# odd name\n")
        (root / "café.txt").write_text("unicode\n")
        (root / "sub" / "deep" / "needle.csv").write_text("a,b\n1,2\n")
        (root / "sub" / "frame_10.png").write_bytes(b"x")
        (root / "sub" / "frame_2.png").write_bytes(b"x")
        (root / ".ssh" / "id_rsa").write_text("PRIVATE")
        (root / ".env").write_text("TOKEN=1")
        (root / "site" / "index.html").write_text("<h1>site</h1>")
        (outside / "report.txt").write_text("outside\n")
        (outside / "loop").symlink_to(outside)
        (secret / "key").write_text("PRIVATE")
        (base / "sibling.txt").write_text("PRIVATE")
        (root / "linked").symlink_to(outside)
        (root / "sneaky").symlink_to(root / ".ssh")
        (root / "sneaky_out").symlink_to(secret)
        (root / "dangling").symlink_to(base / "gone")
        cls.root = root

        shelf_root = Root(str(root), cls.hidden)
        index = SearchIndex(shelf_root)
        handler = shelf.make_handler(shelf_root, index)
        cls.server = shelf.Server(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        index.refresh()
        while index.building or not index.built_at:
            time.sleep(0.01)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def get(self, path, method="GET", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest(method, path, skip_accept_encoding=True)
        for key, value in (headers or {}).items():
            conn.putheader(key, value)
        conn.endheaders()
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body

    def api(self, name, **params):
        query = "&".join("{}={}".format(k, quote(v, safe="")) for k, v in params.items())
        response, body = self.get(f"/__shelf/api/{name}?{query}")
        return response.status, json.loads(body)


class Access(ServerCase):
    def test_traversal_is_refused(self):
        attacks = [
            "/../sibling.txt",
            "/..%2fsibling.txt",
            "/%2e%2e/sibling.txt",
            "/sub/../../sibling.txt",
            "/sub/%2e%2e/%2e%2e/sibling.txt",
            "/..%5csibling.txt",
            "//../sibling.txt",
            "/hello.txt%00.png",
        ]
        for path in attacks:
            response, body = self.get(path)
            self.assertNotEqual(response.status, 200, path)
            self.assertNotIn(b"PRIVATE", body, path)

    def test_traversal_through_api_is_refused(self):
        for name in ("list", "stat"):
            for path in ("..", "../.private", "sub/../..", "/etc", "../sibling.txt"):
                status, _ = self.api(name, path=path)
                if path == "/etc":
                    # A leading slash means the root here, so this is just a missing folder.
                    self.assertEqual(status, 404)
                else:
                    self.assertEqual(status, 404, path)

    def test_dotfiles_are_hidden(self):
        for path in ("/.env", "/.ssh/id_rsa", "/.ssh/", "/%2Essh/id_rsa", "/sub/../.env"):
            response, body = self.get(path)
            self.assertEqual(response.status, 404, path)
            self.assertNotIn(b"PRIVATE", body)
        _, data = self.api("list", path="")
        names = [entry["name"] for entry in data["entries"]]
        self.assertNotIn(".env", names)
        self.assertNotIn(".ssh", names)

    def test_symlink_cannot_reach_dotfiles(self):
        for path in ("/sneaky/id_rsa", "/sneaky_out/key"):
            response, body = self.get(path)
            self.assertEqual(response.status, 404, path)
            self.assertNotIn(b"PRIVATE", body)
        _, data = self.api("list", path="")
        names = [entry["name"] for entry in data["entries"]]
        self.assertNotIn("sneaky", names)
        self.assertNotIn("sneaky_out", names)

    def test_symlink_out_of_root_works(self):
        response, body = self.get("/linked/report.txt")
        self.assertEqual((response.status, body), (200, b"outside\n"))
        _, data = self.api("list", path="")
        entry = next(e for e in data["entries"] if e["name"] == "linked")
        self.assertTrue(entry["dir"])

    def test_dangling_symlink_is_left_out(self):
        _, data = self.api("list", path="")
        self.assertNotIn("dangling", [entry["name"] for entry in data["entries"]])

    def test_writes_are_rejected(self):
        for method in ("POST", "PUT", "DELETE"):
            response, _ = self.get("/hello.txt", method=method)
            self.assertEqual(response.status, 501, method)
        self.assertEqual((self.root / "hello.txt").read_bytes(), b"0123456789")

    def test_redirect_cannot_leave_the_host(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "//evil.example/%2e%2e/sub")
        response = conn.getresponse()
        response.read()
        conn.close()
        self.assertNotIn("evil.example", response.getheader("Location") or "")

    def test_static_cannot_escape(self):
        for name in ("../server.py", "..%2fserver.py", "vendor/../../server.py"):
            response, _ = self.get("/__shelf/static/" + name)
            self.assertEqual(response.status, 404, name)


class HiddenFlag(ServerCase):
    hidden = True

    def test_flag_reveals_dotfiles(self):
        response, body = self.get("/.env")
        self.assertEqual((response.status, body), (200, b"TOKEN=1"))
        _, data = self.api("list", path="")
        self.assertIn(".ssh", [entry["name"] for entry in data["entries"]])


class Files(ServerCase):
    def test_natural_url_serves_raw_file(self):
        response, body = self.get("/hello.txt")
        self.assertEqual((response.status, body), (200, b"0123456789"))
        self.assertEqual(response.getheader("Content-Type"), "text/plain; charset=utf-8")
        self.assertEqual(response.getheader("Accept-Ranges"), "bytes")

    def test_awkward_names(self):
        response, body = self.get("/" + quote("a b#c?d%e.md"))
        self.assertEqual((response.status, body), (200, b"# odd name\n"))
        response, body = self.get("/" + quote("café.txt"))
        self.assertEqual((response.status, body), (200, b"unicode\n"))

    def test_head_has_length_and_no_body(self):
        response, body = self.get("/hello.txt", method="HEAD")
        self.assertEqual(response.getheader("Content-Length"), "10")
        self.assertEqual(body, b"")

    def test_ranges(self):
        cases = {
            "bytes=0-3": (206, b"0123", "bytes 0-3/10"),
            "bytes=4-": (206, b"456789", "bytes 4-9/10"),
            "bytes=-2": (206, b"89", "bytes 8-9/10"),
            "bytes=8-100": (206, b"89", "bytes 8-9/10"),
            "bytes=-100": (206, b"0123456789", "bytes 0-9/10"),
        }
        for header, (status, expected, content_range) in cases.items():
            response, body = self.get("/hello.txt", headers={"Range": header})
            self.assertEqual((response.status, body), (status, expected), header)
            self.assertEqual(response.getheader("Content-Range"), content_range)

    def test_unsatisfiable_ranges(self):
        for header in ("bytes=10-", "bytes=5-2", "bytes=-0"):
            response, _ = self.get("/hello.txt", headers={"Range": header})
            self.assertEqual(response.status, 416, header)
            self.assertEqual(response.getheader("Content-Range"), "bytes */10")

    def test_odd_ranges_fall_back_to_whole_file(self):
        for header in ("bytes=0-1,3-4", "items=0-1", "nonsense"):
            response, body = self.get("/hello.txt", headers={"Range": header})
            self.assertEqual((response.status, body), (200, b"0123456789"), header)

    def test_range_on_empty_file(self):
        response, _ = self.get("/empty.txt", headers={"Range": "bytes=0-99"})
        self.assertEqual(response.status, 416)
        response, body = self.get("/empty.txt")
        self.assertEqual((response.status, body), (200, b""))

    def test_conditional_get(self):
        first, _ = self.get("/hello.txt")
        etag = first.getheader("ETag")
        response, body = self.get("/hello.txt", headers={"If-None-Match": etag})
        self.assertEqual((response.status, body), (304, b""))

    def test_stale_if_range_returns_whole_file(self):
        headers = {"Range": "bytes=0-1", "If-Range": '"stale"'}
        response, body = self.get("/hello.txt", headers=headers)
        self.assertEqual((response.status, body), (200, b"0123456789"))

    def test_dropped_connections_stay_quiet(self):
        import contextlib
        import io
        import struct

        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            for _ in range(3):
                sock = socket.create_connection(("127.0.0.1", self.port))
                sock.sendall(b"GET /hello.txt HTTP/1.1\r\nHost: x\r\n\r\n")
                sock.recv(100)
                # Linger 0 makes close() send a reset, as a browser dropping the socket does.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                sock.close()
            time.sleep(0.3)
            _response, body = self.get("/hello.txt")
        self.assertEqual(body, b"0123456789")
        self.assertNotIn("Traceback", captured.getvalue())

    def test_keep_alive_survives_several_requests(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        for _ in range(3):
            conn.request("GET", "/hello.txt")
            self.assertEqual(conn.getresponse().read(), b"0123456789")
        conn.close()


class Routing(ServerCase):
    def test_root_is_the_app(self):
        response, body = self.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"app.js", body)
        self.assertIn("default-src", response.getheader("Content-Security-Policy"))

    def test_folder_redirects_into_the_app(self):
        response, _ = self.get("/sub/deep")
        self.assertEqual(response.status, 302)
        self.assertEqual(response.getheader("Location"), "/#/sub/deep/")

    def test_folder_in_a_frame_acts_like_a_web_server(self):
        frame = {"Sec-Fetch-Dest": "iframe"}
        response, _ = self.get("/site", headers=frame)
        self.assertEqual((response.status, response.getheader("Location")), (302, "/site/"))
        response, body = self.get("/site/", headers=frame)
        self.assertEqual(body, b"<h1>site</h1>")
        response, body = self.get("/sub/", headers=frame)
        self.assertEqual(body, shelf.FRAME_FOLDER_PAGE)

    def test_static_revalidates(self):
        response, body = self.get("/__shelf/static/js/app.js")
        self.assertEqual(response.status, 200)
        self.assertTrue(body)
        again, _ = self.get(
            "/__shelf/static/js/app.js", headers={"If-None-Match": response.getheader("ETag")}
        )
        self.assertEqual(again.status, 304)


class Api(ServerCase):
    def test_list_sorts_folders_first_then_naturally(self):
        _, data = self.api("list", path="sub")
        self.assertEqual(
            [e["name"] for e in data["entries"]], ["deep", "frame_2.png", "frame_10.png"]
        )

    def test_stat(self):
        status, data = self.api("stat", path="hello.txt")
        self.assertEqual((status, data["type"], data["size"]), (200, "file", 10))
        status, _ = self.api("stat", path="nope")
        self.assertEqual(status, 404)

    def test_list_on_a_file(self):
        status, _ = self.api("list", path="hello.txt")
        self.assertEqual(status, 400)

    def test_search_finds_nested_and_symlinked_files(self):
        _, data = self.api("search", q="needle")
        self.assertEqual(data["results"], ["sub/deep/needle.csv"])
        _, data = self.api("search", q="report")
        self.assertEqual(data["results"], ["linked/report.txt"])

    def test_search_matches_all_terms_across_the_path(self):
        _, data = self.api("search", q="deep CSV")
        self.assertEqual(data["results"], ["sub/deep/needle.csv"])
        _, data = self.api("search", q="deep missing")
        self.assertEqual(data["results"], [])

    def test_search_marks_folders_and_ranks_exact_names_first(self):
        _, data = self.api("search", q="deep")
        self.assertEqual(data["results"][0], "sub/deep/")

    def test_search_never_reveals_hidden_paths(self):
        for term in ("id_rsa", ".env", "key", "sneaky"):
            _, data = self.api("search", q=term)
            self.assertEqual(data["results"], [], term)

    def test_search_survives_symlink_loops(self):
        _, data = self.api("search", q="loop")
        self.assertEqual(data["results"], ["linked/loop/"])

    def test_blank_search(self):
        _, data = self.api("search", q="   ")
        self.assertEqual(data["results"], [])


class Helpers(unittest.TestCase):
    def test_hidden_rule_only_counts_what_is_below_the_shared_path(self):
        root = Root("/home/me/.cache/demo/tree", False)
        self.assertTrue(root.allowed_target("/home/me/.cache/demo/tree"))
        self.assertTrue(root.allowed_target("/home/me/.cache/demo/tree/a/b.txt"))
        self.assertTrue(root.allowed_target("/home/me/.cache/demo/other/b.txt"))
        self.assertTrue(root.allowed_target("/mnt/data/exp"))
        self.assertFalse(root.allowed_target("/home/me/.cache/demo/tree/.git/config"))
        self.assertFalse(root.allowed_target("/home/me/.ssh/id_rsa"))
        self.assertFalse(root.allowed_target("/mnt/data/.private/key"))

    def test_natural_key_compares_the_stem_first(self):
        names = ["clip10.mp4", "clip2.webm", "clip.mp4", "frame_10.png", "frame_2.png"]
        self.assertEqual(
            sorted(names, key=natural_key),
            ["clip.mp4", "clip2.webm", "clip10.mp4", "frame_2.png", "frame_10.png"],
        )

    def test_natural_key_handles_non_decimal_digits(self):
        names = ["²", "a10", "a2", "A1"]
        self.assertEqual(sorted(names, key=natural_key), ["A1", "a2", "a10", "²"])

    def test_args(self):
        parse = parse_args
        self.assertEqual((parse(["8099"]).port, parse(["8099"]).directory), (8099, None))
        self.assertEqual((parse(["/tmp"]).port, parse(["/tmp"]).directory), (None, "/tmp"))
        args = parse(["8099", "/tmp"])
        self.assertEqual((args.port, args.directory), (8099, "/tmp"))

    def test_chosen_port_in_use_is_an_error(self):
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            with self.assertRaises(SystemExit):
                shelf.bind(shelf.Handler, "127.0.0.1", port, fixed=True)
            found = shelf.bind(shelf.Handler, "127.0.0.1", port, fixed=False)
            self.assertNotEqual(found.server_address[1], port)
            found.server_close()


if __name__ == "__main__":
    unittest.main()
