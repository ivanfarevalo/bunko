"""The server registry and `bunko link`.

Run with: python3 -m unittest discover -s tests
"""

import io
import json
import os
import pathlib
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bunko import cli, registry


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(os.path.realpath(self.tmp.name))
        patcher = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.dir / "run")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        self.addCleanup(self.listener.close)
        self.site = self.dir / "site"
        (self.site / "sub dir").mkdir(parents=True)
        (self.site / "sub dir" / "notes #1.md").write_text("x")
        (self.site / ".secret").mkdir()
        (self.site / ".secret" / "key").write_text("x")
        (self.dir / "outside.txt").write_text("x")

    def tearDown(self):
        self.tmp.cleanup()

    def register(self, root, url="http://localhost:1/", hidden=False):
        return registry.register(str(root), hidden, "127.0.0.1", self.port, url)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as exit:
                code = exit.code if isinstance(exit.code, int) else 1
                err.write(str(exit.code) if not isinstance(exit.code, int) else "")
        return code, out.getvalue().strip(), err.getvalue().strip()

    def test_register_and_unregister(self):
        path = self.register(self.site)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual([record["root"] for record in registry.running()], [str(self.site)])
        registry.unregister(path)
        self.assertEqual(registry.running(), [])

    def test_stale_records_are_dropped(self):
        folder = self.dir / "run" / "bunko" / "servers"
        folder.mkdir(parents=True)
        dead = {
            "pid": 999_999_999,
            "root": "/",
            "hidden": False,
            "bind": "127.0.0.1",
            "port": self.port,
            "url": "x",
        }
        closed = dict(dead, pid=os.getpid(), port=1)  # a live process whose port answers nothing
        (folder / "1.json").write_text(json.dumps(dead))
        (folder / "2.json").write_text(json.dumps(closed))
        (folder / "3.json").write_text("not json")
        self.assertEqual(registry.running(), [])
        self.assertEqual(list(folder.iterdir()), [])

    def test_link_to_a_file_with_a_line(self):
        self.register(self.site, "http://box:8100/")
        code, out, _ = self.run_cli(
            "link", str(self.site / "sub dir" / "notes #1.md"), "--line", "7"
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, "http://box:8100/#/sub%20dir/notes%20%231.md?line=7")
        self.assertEqual(unquote(out.split("#/", 1)[1].split("?")[0]), "sub dir/notes #1.md")

    def test_link_to_the_root_and_the_current_folder(self):
        self.register(self.site, "http://box:8100/")
        self.assertEqual(self.run_cli("link", str(self.site))[1], "http://box:8100/#/")
        cwd = os.getcwd()
        os.chdir(self.site / "sub dir")
        try:
            self.assertEqual(self.run_cli("link")[1], "http://box:8100/#/sub%20dir")
        finally:
            os.chdir(cwd)

    def test_the_innermost_server_wins(self):
        self.register(self.dir, "http://outer/")
        with mock.patch("os.getpid", return_value=os.getppid()):
            self.register(self.site, "http://inner/")
        self.assertEqual(
            self.run_cli("link", str(self.site / "sub dir"))[1], "http://inner/#/sub%20dir"
        )
        self.assertEqual(
            self.run_cli("link", str(self.dir / "outside.txt"))[1], "http://outer/#/outside.txt"
        )

    def test_no_server_says_how_to_start_one(self):
        self.register(self.site)
        code, _, err = self.run_cli("link", str(self.dir / "outside.txt"))
        self.assertEqual(code, 1)
        self.assertIn("no running bunko serves", err)
        self.assertIn(f"bunko {self.dir}", err)

    def test_hidden_paths_unless_the_server_shows_them(self):
        self.register(self.site)
        code, _, err = self.run_cli("link", str(self.site / ".secret" / "key"))
        self.assertEqual(code, 1)
        self.assertIn("dotfile", err)
        registry.unregister(self.register(self.site))
        self.register(self.site, "http://box/", hidden=True)
        self.assertEqual(
            self.run_cli("link", str(self.site / ".secret" / "key"))[1], "http://box/#/.secret/key"
        )

    def test_missing_paths(self):
        code, _, err = self.run_cli("link", str(self.dir / "nope"))
        self.assertEqual(code, 1)
        self.assertIn("no such file", err)

    def test_symlinked_paths_resolve_to_the_served_folder(self):
        self.register(self.site, "http://box/")
        link = self.dir / "shortcut"
        link.symlink_to(self.site / "sub dir")
        self.assertEqual(
            self.run_cli("link", str(link / "notes #1.md"))[1],
            "http://box/#/sub%20dir/notes%20%231.md",
        )

    def test_servers_lists_them(self):
        self.assertEqual(self.run_cli("servers")[1], "No bunko servers running.")
        self.register(self.site, "http://box:8100/")
        self.assertIn(f"http://box:8100/  {self.site}", self.run_cli("servers")[1])


class PublicUrl(unittest.TestCase):
    def test_addresses(self):
        with mock.patch("socket.gethostname", return_value="box"):
            self.assertEqual(
                registry.public_url("127.0.0.1", 8100, "open"), "http://localhost:8100/"
            )
            self.assertEqual(registry.public_url("0.0.0.0", 8100, "token"), "http://box:8100/")
            self.assertEqual(
                registry.public_url("100.64.0.1", 8100, "open"), "http://100.64.0.1:8100/"
            )
            self.assertEqual(registry.public_url("fd7a::1", 8100, "open"), "http://[fd7a::1]:8100/")

    def test_tailscale_name(self):
        status = json.dumps({"Self": {"DNSName": "box.tail1234.ts.net."}}).encode()
        done = mock.Mock(stdout=status)
        with mock.patch("subprocess.run", return_value=done):
            self.assertEqual(
                registry.public_url("127.0.0.1", 8100, "tailscale"),
                "https://box.tail1234.ts.net:8100/",
            )
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertEqual(
                registry.public_url("127.0.0.1", 8100, "tailscale"), "http://localhost:8100/"
            )

    def test_public_url_must_be_http(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            cli.parse_args(["--public-url", "box:8100"])
        self.assertEqual(cli.parse_args(["--public-url", "https://x/"]).public_url, "https://x/")


if __name__ == "__main__":
    unittest.main()
