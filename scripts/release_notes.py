#!/usr/bin/env python3
"""Print one version's section of CHANGELOG.md: python3 scripts/release_notes.py 0.3.0"""

import pathlib
import re
import sys

changelog = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"
version = sys.argv[1].lstrip("v")
sections = re.split(r"^## ", changelog.read_text(), flags=re.M)
for section in sections[1:]:
    heading, _, body = section.partition("\n")
    if heading.strip() == version:
        print(body.strip())
        break
else:
    sys.exit(f"No CHANGELOG.md section for {version}")
