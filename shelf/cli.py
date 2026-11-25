"""Command line: `shelf [PORT] [DIR] [options]`, plus `shelf service` and `shelf token`."""
from __future__ import annotations

import argparse
import os
import socket
import sys

from . import __version__
from .access import Access, TokenStore, is_loopback
from .contents import ContentSearch
from .media import Prober, Thumbnails
from .places import Places
from .server import DEFAULT_PORT, SKIP_DIRS, Handler, Root, SearchIndex, bind

EPILOG = """examples:
  shelf                          serve the current folder on port 8000 (or the next free one)
  shelf 8099 ~/reports           choose the port and folder
  shelf 8100 ~/reports -b 127.0.0.1 --allow-user you@example.com
                                 recommended on a shared network: put `tailscale serve` in front
  shelf 8100 ~/reports --token   require an access token (shelf prints the link)

subcommands:
  shelf service install|uninstall|status|logs|restart|list   run as a systemd user service
  shelf token [--new] [--port N]                             show or replace the access token

docs: https://github.com/ivanfarevalo/shelf/tree/main/docs"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shelf",
        description="Browse a folder in a Notion-style web UI. Read-only.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target", nargs="*", help="a port number and/or a directory")
    parser.add_argument("-p", "--port", type=int, help="port (default %d)" % DEFAULT_PORT)
    parser.add_argument("-d", "--directory", help="directory to serve (default: current)")
    parser.add_argument("-b", "--bind", default="0.0.0.0", help="address to listen on (default: all, like http.server)")
    parser.add_argument("--hidden", action="store_true", help="also show and serve dotfiles")

    access = parser.add_argument_group("access control (see docs/security.md)")
    access.add_argument("--allow-user", action="append", default=[], metavar="LOGIN",
                        help="allow this Tailscale user; repeat for more, wildcards allowed (*@example.com). "
                             "Requires -b 127.0.0.1 and `tailscale serve` in front")
    access.add_argument("--token", action="store_true", help="require an access token")
    access.add_argument("--new-token", action="store_true", help="replace the token before starting (implies --token)")
    access.add_argument("--token-file", metavar="PATH", help="where the token lives (default ~/.config/shelf/token)")

    media = parser.add_argument_group("media")
    media.add_argument("--no-thumbnails", action="store_true", help="don't generate thumbnails with ffmpeg")
    media.add_argument("--cache-dir", metavar="PATH", help="thumbnail cache (default ~/.cache/shelf)")

    parser.add_argument("-v", "--verbose", action="store_true", help="log every request")
    parser.add_argument("--version", action="version", version="shelf " + __version__)
    return parser


def parse_args(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    for item in args.target:
        if item.isdecimal() and not os.path.isdir(item):
            if args.port is not None:
                parser.error("more than one port given")
            args.port = int(item)
        elif args.directory is None:
            args.directory = item
        else:
            parser.error("more than one directory given")
    if args.new_token:
        args.token = True
    if args.allow_user and args.token:
        parser.error("choose one of --allow-user and --token")
    if args.allow_user and not is_loopback(args.bind):
        parser.error(
            "--allow-user trusts identity headers from `tailscale serve`, so shelf must listen "
            "only on loopback. Add -b 127.0.0.1 (see docs/security.md)."
        )
    return args


def token_command(argv) -> None:
    parser = argparse.ArgumentParser(prog="shelf token", description="Show or replace the access token.")
    parser.add_argument("--new", action="store_true", help="replace it; every signed-in browser must sign in again")
    parser.add_argument("--port", type=int, help="print a sign-in link for this port")
    parser.add_argument("--host", default=socket.gethostname(), help="host name for the link")
    parser.add_argument("--token-file", metavar="PATH")
    args = parser.parse_args(argv)
    store = TokenStore(args.token_file)
    token = store.rotate() if args.new else store.ensure()
    if args.new:
        print("New token saved to %s. Running servers pick it up on the next request." % store.describe())
    if args.port:
        print("http://%s:%d/?token=%s" % (args.host, args.port, token))
    else:
        print(token)


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["service"]:
        from .service import main as service_main
        return service_main(argv[1:])
    if argv[:1] == ["token"]:
        return token_command(argv[1:])

    args = parse_args(argv)
    directory = os.path.abspath(os.path.expanduser(args.directory or "."))
    if not os.path.isdir(directory):
        sys.exit("shelf: not a directory: " + directory)

    root = Root(directory, args.hidden)
    index = SearchIndex(root)
    tokens = TokenStore(args.token_file) if args.token else None
    if tokens:
        if args.new_token:
            tokens.rotate()
        else:
            tokens.ensure()
    handler = type("BoundHandler", (Handler,), {
        "root": root,
        "index": index,
        "contents": ContentSearch(root, index, SKIP_DIRS),
        "thumbs": Thumbnails(args.cache_dir, enabled=not args.no_thumbnails),
        "prober": Prober(),
        "places": Places(root),
    })
    server = bind(handler, args.bind, args.port or DEFAULT_PORT, args.port is not None)
    port = server.server_address[1]
    mode = "tailscale" if args.allow_user else "token" if tokens else "open"
    handler.access = Access(mode, port, tokens, args.allow_user)
    server.verbose = args.verbose
    index.refresh()

    exposed = args.bind in ("0.0.0.0", "::")
    host = "localhost" if exposed else args.bind
    notes = ["read-only"]
    if args.hidden:
        notes.append("dotfiles visible")
    notes.append({"open": "no access control", "token": "token required", "tailscale": "Tailscale users: " + ", ".join(args.allow_user)}[mode])
    print("shelf %s  serving %s (%s)" % (__version__, root.real, "; ".join(notes)))
    links = ["http://%s:%d/" % (host, port)]
    if exposed:
        links.append("http://%s:%d/" % (socket.gethostname(), port))
    if mode == "token":
        if sys.stdout.isatty():
            token = tokens.current()
            links = [link + "?token=" + token for link in links]
        else:
            # Never write the secret into service logs.
            print("  token: run `shelf token --port %d` to print a sign-in link" % port)
    for link in links:
        print("  " + link)
    if mode == "tailscale":
        print("  put Tailscale in front:  tailscale serve --bg --https=%d http://127.0.0.1:%d" % (port, port))
    if mode == "open" and not is_loopback(args.bind):
        print("  warning: anyone who can reach this address can read these files. See docs/security.md.")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
