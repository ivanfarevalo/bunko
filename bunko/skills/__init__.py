"""Skills Bunko ships for AI agents, and installing them where each agent looks.

One source file per skill. Claude Code reads skills from ~/.claude/skills/NAME/SKILL.md;
Codex reads custom prompts from ~/.codex/prompts/NAME.md. CLAUDE_CONFIG_DIR and
CODEX_HOME move those folders, as they do for the agents themselves.
"""

from __future__ import annotations

import argparse
import os
import pkgutil

SKILLS = ("report",)
AGENTS = ("claude", "codex")


def source(name: str) -> str:
    return pkgutil.get_data(__package__, f"{name}/SKILL.md").decode("utf-8")


def target(agent: str, name: str) -> str:
    if agent == "claude":
        base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
        return os.path.join(base, "skills", name, "SKILL.md")
    base = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    return os.path.join(base, "prompts", f"{name}.md")


def for_agent(agent: str, text: str) -> str:
    """Codex prompts take only a description in their front matter."""
    if agent != "codex" or not text.startswith("---\n"):
        return text
    front, _, body = text[4:].partition("\n---\n")
    description = next((line for line in front.splitlines() if line.startswith("description:")), "")
    return f"---\n{description}\n---\n{body}" if description else body


def install(agents=AGENTS, names=SKILLS) -> list:
    """Write each skill for each agent; return what was written."""
    written = []
    for agent in agents:
        for name in names:
            path = target(agent, name)
            text = for_agent(agent, source(name))
            previous = None
            if os.path.exists(path):
                with open(path, encoding="utf-8") as handle:
                    previous = handle.read()
            if previous != text:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as out:
                    out.write(text)
            status = "unchanged" if previous == text else "updated" if previous else "installed"
            written.append({"agent": agent, "skill": name, "path": path, "status": status})
    return written


def main(argv: list) -> None:
    parser = argparse.ArgumentParser(
        prog="bunko skill",
        description="Install Bunko's skills for AI agents: /report for Claude Code, and a report prompt for Codex.",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("install", help="install or update the skills")
    add.add_argument("--agent", choices=(*AGENTS, "all"), default="all")
    show = sub.add_parser("show", help="print a skill")
    show.add_argument("name", nargs="?", default="report", choices=SKILLS)
    args = parser.parse_args(argv)
    if args.action == "show":
        print(source(args.name), end="")
        return
    agents = AGENTS if args.agent == "all" else (args.agent,)
    for item in install(agents):
        print(f"{item['status']:<9} {item['agent']:<6} {item['path']}")
    print("Updating Bunko? Run this again to update the skills too.")
