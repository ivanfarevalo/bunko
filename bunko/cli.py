"""Command line: `bunko [PORT] [DIR] [options]`, plus `bunko service` and `bunko token`."""

from __future__ import annotations

import argparse
import os
import socket
import sys

from . import __version__
from .access import Access, TokenStore, is_loopback
from .contents import ContentSearch
from .index import SearchIndex
from .media import Prober, Thumbnails
from .paths import Root
from .places import Places
from .server import DEFAULT_PORT, Server, bind, make_handler

EPILOG = """examples:
  bunko                          serve the current folder on port 8000 (or the next free one)
  bunko 8099 ~/reports           choose the port and folder
  bunko 8100 ~/reports --allow-user you@example.com
                                 recommended on a shared network: put `tailscale serve` in front
  bunko 8100 ~/reports -b 0.0.0.0 --token
                                 reachable from any network, with an access token

subcommands:
  bunko service install|uninstall|status|logs|restart|list   run as a systemd user service
  bunko token [--new] [--port N]                             show or replace the access token

docs: https://github.com/ivanfarevalo/bunko/tree/main/docs"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bunko",
        description="Serve a folder read-only, with a browser UI that renders its files.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target", nargs="*", help="a port number and/or a directory")
    parser.add_argument("-p", "--port", type=int, help=f"port (default {DEFAULT_PORT})")
    parser.add_argument("-d", "--directory", help="directory to serve (default: current)")
    parser.add_argument(
        "-b",
        "--bind",
        default="127.0.0.1",
        help="address to listen on (default: 127.0.0.1, this machine only; 0.0.0.0 for every network)",
    )
    parser.add_argument("--hidden", action="store_true", help="also show and serve dotfiles")

    access = parser.add_argument_group("access control (see docs/security.md)")
    access.add_argument(
        "--allow-user",
        action="append",
        default=[],
        metavar="LOGIN",
        help="allow this Tailscale user; repeat for more, wildcards allowed (*@example.com). "
        "Requires -b 127.0.0.1 and `tailscale serve` in front",
    )
    access.add_argument("--token", action="store_true", help="require an access token")
    access.add_argument(
        "--new-token",
        action="store_true",
        help="replace the token before starting (implies --token)",
    )
    access.add_argument(
        "--token-file", metavar="PATH", help="where the token lives (default ~/.config/bunko/token)"
    )

    media = parser.add_argument_group("media")
    media.add_argument(
        "--no-thumbnails", action="store_true", help="don't generate thumbnails with ffmpeg"
    )
    media.add_argument(
        "--cache-dir", metavar="PATH", help="thumbnail cache (default ~/.cache/bunko)"
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="log every request")
    parser.add_argument("--version", action="version", version="bunko " + __version__)
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
            "--allow-user trusts identity headers from `tailscale serve`, so bunko must listen "
            "only on loopback. Add -b 127.0.0.1 (see docs/security.md)."
        )
    return args


def token_command(argv) -> None:
    parser = argparse.ArgumentParser(
        prog="bunko token", description="Show or replace the access token."
    )
    parser.add_argument(
        "--new", action="store_true", help="replace it; every signed-in browser must sign in again"
    )
    parser.add_argument("--port", type=int, help="print a sign-in link for this port")
    parser.add_argument("--host", default=socket.gethostname(), help="host name for the link")
    parser.add_argument("--token-file", metavar="PATH")
    args = parser.parse_args(argv)
    store = TokenStore(args.token_file)
    token = store.rotate() if args.new else store.ensure()
    if args.new:
        print(
            f"New token saved to {store.describe()}. Running servers pick it up on the next request."
        )
    if args.port:
        print(f"http://{args.host}:{args.port}/?token={token}")
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
    server = build_server(args)
    print_banner(server, args)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return None


def access_mode(args) -> str:
    return "tailscale" if args.allow_user else "token" if args.token else "open"


def build_server(args) -> Server:
    """Set up the folder, its services, and the listening socket."""
    directory = os.path.abspath(os.path.expanduser(args.directory or "."))
    if not os.path.isdir(directory):
        sys.exit("bunko: not a directory: " + directory)
    root = Root(directory, args.hidden)
    index = SearchIndex(root)
    tokens = TokenStore(args.token_file) if args.token else None
    if tokens and args.new_token:
        tokens.rotate()
    elif tokens:
        tokens.ensure()
    handler = make_handler(
        root,
        index,
        contents=ContentSearch(root, index),
        thumbs=Thumbnails(args.cache_dir, enabled=not args.no_thumbnails),
        prober=Prober(),
        places=Places(root),
    )
    server = bind(handler, args.bind, args.port or DEFAULT_PORT, args.port is not None)
    # The cookie name includes the port, which is only known once bound.
    handler.access = Access(access_mode(args), server.server_address[1], tokens, args.allow_user)
    server.verbose = args.verbose
    index.refresh()
    return server


def print_banner(server: Server, args) -> None:
    """Say what is served, where, and how it's protected."""
    handler = server.RequestHandlerClass
    port = server.server_address[1]
    mode = handler.access.mode
    notes = ["read-only"]
    if args.hidden:
        notes.append("dotfiles visible")
    notes.append(
        {
            "open": "no access control",
            "token": "token required",
            "tailscale": "Tailscale users: " + ", ".join(args.allow_user),
        }[mode]
    )
    print(f"bunko {__version__}  serving {handler.root.real} ({'; '.join(notes)})")

    exposed = args.bind in ("0.0.0.0", "::")
    links = [f"http://{'localhost' if exposed else args.bind}:{port}/"]
    if exposed:
        links.append(f"http://{socket.gethostname()}:{port}/")
    if mode == "token":
        if sys.stdout.isatty():
            token = handler.access.tokens.current()
            links = [link + "?token=" + token for link in links]
        else:
            # Never write the secret into service logs.
            print(f"  token: run `bunko token --port {port}` to print a sign-in link")
    for link in links:
        print("  " + link)
    if mode == "tailscale":
        print(
            f"  put Tailscale in front:  tailscale serve --bg --https={port} http://127.0.0.1:{port}"
        )
    if is_loopback(args.bind) and mode != "tailscale":
        print(
            f"  only this machine can connect. From elsewhere: ssh -L {port}:localhost:{port} "
            f"{socket.gethostname()}, or choose an address with -b (see docs/security.md)."
        )
    if mode == "open" and not is_loopback(args.bind):
        print(
            "  warning: anyone who can reach this address can read these files. See docs/security.md."
        )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
