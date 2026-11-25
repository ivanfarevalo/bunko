#!/usr/bin/env python3
"""Build dist/shelf.pyz: one file that runs on any machine with python3."""
import pathlib
import zipapp

repo = pathlib.Path(__file__).resolve().parent.parent
target = repo / "dist" / "shelf.pyz"
target.parent.mkdir(exist_ok=True)


def keep(path: pathlib.Path) -> bool:
    return path.parts[0] == "shelf" and "__pycache__" not in path.parts


zipapp.create_archive(
    repo,
    target,
    interpreter="/usr/bin/env python3",
    main="shelf.cli:main",
    filter=keep,
    compressed=True,
)
print("%s (%d KB)" % (target, target.stat().st_size // 1024))
