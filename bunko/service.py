"""`bunko service ...`: run bunko as a systemd user service.

A user service starts at login (or at boot, with lingering enabled), restarts
after a crash, and logs to the journal. It needs no root.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys

from .storage import config_home


def unit_dir() -> str:
    return os.path.join(config_home(), "systemd", "user")


def unit_name(name: str) -> str:
    return f"bunko-{name}.service"


def launcher() -> list:
    """The command that starts this same bunko, wherever it was installed.

    -I (isolated) keeps the working directory off sys.path: services start in
    the home directory, where a checkout named "bunko" would otherwise shadow
    the installed package. It also ignores PYTHON* variables, so -u replaces
    PYTHONUNBUFFERED for prompt journal logs.
    """
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if script.endswith(".pyz") and os.path.isfile(script):
        return [sys.executable, "-I", "-u", script]
    return [sys.executable, "-I", "-u", "-m", "bunko"]


def serve_arguments(args: list) -> list:
    """Validate serve arguments and make paths absolute, since services start in ~."""
    from .cli import parse_args

    parsed = parse_args(list(args))
    out = []
    if parsed.port is not None:
        out += ["--port", str(parsed.port)]
    directory = os.path.abspath(os.path.expanduser(parsed.directory or "."))
    out += ["--directory", directory]
    out += ["--bind", parsed.bind]
    if parsed.hidden:
        out.append("--hidden")
    for user in parsed.allow_user:
        out += ["--allow-user", user]
    if parsed.token:
        out.append("--token")
    if parsed.token_file:
        out += ["--token-file", os.path.abspath(os.path.expanduser(parsed.token_file))]
    if parsed.no_thumbnails:
        out.append("--no-thumbnails")
    if parsed.cache_dir:
        out += ["--cache-dir", os.path.abspath(os.path.expanduser(parsed.cache_dir))]
    return out


def render_unit(name: str, command: list) -> str:
    # systemd unit files take their own quoting; shlex quoting is compatible for
    # ordinary paths, and % must be doubled.
    exec_start = " ".join(shlex.quote(part) for part in command).replace("%", "%%")
    return (
        "[Unit]\n"
        f"Description=bunko file server ({name})\n"
        "Documentation=https://github.com/ivanfarevalo/bunko\n"
        "\n"
        "[Service]\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        # Binding to a Tailscale address fails until tailscaled is up after boot;
        # retrying covers that without ordering on a system unit we cannot see.
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def systemctl(*args, check=True):
    return subprocess.run(["systemctl", "--user", *args], check=check)


def linger_enabled() -> bool | None:
    try:
        out = subprocess.run(
            ["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.strip().endswith("yes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bunko service",
        description="Run bunko as a systemd user service.",
        epilog="Example: bunko service install --name docs -- 8100 ~/docs --allow-user you@example.com",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    install = sub.add_parser("install", help="create, enable and start a service")
    install.add_argument("--name", default="default", help="service name (default: default)")
    install.add_argument(
        "--print", action="store_true", help="print the unit file instead of installing it"
    )
    install.add_argument("serve", nargs=argparse.REMAINDER, help="bunko arguments, after --")
    for action in ("uninstall", "status", "logs", "restart"):
        command = sub.add_parser(action, help=f"{action} a service")
        command.add_argument("--name", default="default")
    sub.add_parser("list", help="list installed bunko services")
    return parser


def main(argv: list) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.action == "list":
        return list_services()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.name):
        parser.error("--name may use letters, digits, '.', '_' and '-' only")
    unit = unit_name(args.name)
    path = os.path.join(unit_dir(), unit)
    if args.action == "install":
        return install(args, unit, path)
    if not os.path.exists(path):
        sys.exit(f"bunko: no service named {args.name!r} ({path})")
    if args.action == "uninstall":
        systemctl("disable", "--now", unit, check=False)
        os.remove(path)
        systemctl("daemon-reload")
        print(f"Removed {unit}")
    elif args.action == "status":
        systemctl("status", "--no-pager", unit, check=False)
    elif args.action == "restart":
        systemctl("restart", unit)
    elif args.action == "logs":
        os.execvp("journalctl", ["journalctl", "--user", "-u", unit, "-f", "-n", "100"])
    return None


def list_services() -> None:
    folder = unit_dir()
    names = []
    if os.path.isdir(folder):
        names = sorted(
            name for name in os.listdir(folder) if re.fullmatch(r"bunko-.+\.service", name)
        )
    for unit in names:
        state = subprocess.run(
            ["systemctl", "--user", "is-active", unit], capture_output=True, text=True
        ).stdout.strip()
        print(f"{unit:<30} {state or 'unknown'}")
    if not names:
        print("No bunko services installed.")


def install(args, unit: str, path: str) -> None:
    serve = args.serve[1:] if args.serve[:1] == ["--"] else args.serve
    text = render_unit(args.name, launcher() + serve_arguments(serve))
    if args.print:
        sys.stdout.write(text)
        return
    if not shutil.which("systemctl"):
        sys.exit(
            "bunko: systemctl not found. Use `bunko service install --print` and adapt the unit, "
            "or run bunko in tmux."
        )
    os.makedirs(unit_dir(), exist_ok=True)
    with open(path, "w") as out:
        out.write(text)
    systemctl("daemon-reload")
    systemctl("enable", "--now", unit)
    print(
        f"Installed {unit}\n"
        f"  unit:   {path}\n"
        f"  status: bunko service status --name {args.name}\n"
        f"  logs:   bunko service logs --name {args.name}"
    )
    if linger_enabled() is False:
        print(
            "\nIt stops when you log out. To keep it running and start it at boot:\n"
            "  loginctl enable-linger $USER"
        )
