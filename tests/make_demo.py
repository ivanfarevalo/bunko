#!/usr/bin/env python3
"""Generate a demo tree covering every viewer: python3 tests/make_demo.py DIR"""

import json
import pathlib
import random
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import office_samples

root = pathlib.Path(sys.argv[1]).resolve()
if root.exists():
    shutil.rmtree(root)
outside = root.parent / (root.name + "-outside")
if outside.exists():
    shutil.rmtree(outside)
for folder in (
    "office",
    "docs",
    "report/assets",
    "images",
    "videos",
    "data",
    "logs",
    "src",
    "many",
    "site/sub",
    ".hidden",
):
    (root / folder).mkdir(parents=True)
outside.mkdir()


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


(root / "README.md").write_text("""# Detector evaluation

Results of the **label audit**. See the [guide](docs/guide.md) or the [report](report/index.html).

| Split   | Precision | Recall |
|---------|----------:|-------:|
| indoor  | 0.912     | 0.874  |
| outdoor | 0.887     | 0.851  |
""")

(root / "docs" / "guide.md").write_text(
    """---
title: Guide
owner: vision
---
# Guide

A paragraph with `inline code`, **bold**, *italic*, a [relative link](../README.md),
an [external link](https://example.com), and a [heading link](#second-section).

![A chart](../images/frame_2.png)

- [x] Done task
- [ ] Open task
  - Nested item

> A quotation, shown as a quote block.

## Second section

```python
def iou(a, b):
    \"\"\"Intersection over union of two boxes.\"\"\"
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    return inter / (area(a) + area(b) - inter)
```

```bash
uv run python train.py --epochs 10
```

| Column | Value |
|--------|-------|
| a      | 1     |

<script>window.__pwned = 1</script>
<img src="x" onerror="window.__pwned = 2">
<a href="javascript:window.__pwned = 3" id="jslink">bad link</a>

## Second section

The duplicate heading above needs its own id.
"""
    + "\n".join(f"Filler paragraph {i}." for i in range(60))
)

(root / "report" / "index.html").write_text("""<!doctype html>
<html><head><title>Report</title><link rel="stylesheet" href="assets/style.css"></head>
<body><h1 id="title">Loading</h1><img src="/images/frame_3.png" width="120" id="abs">
<p><a id="next" href="page2.html">Next page</a> <a id="folder" href="../data/">Data folder</a>
<a id="bust" href="#" onclick="try{top.location='/x'}catch(e){document.title='blocked'};return false">bust</a></p>
<script>fetch('assets/data.json').then(r=>r.json()).then(d=>{document.getElementById('title').textContent=d.title})</script>
</body></html>""")
(root / "report" / "page2.html").write_text("<!doctype html><h1 id=p2>Page two</h1>")
(root / "report" / "assets" / "style.css").write_text(
    "h1{color:rgb(200,30,30);font-family:sans-serif}"
)
(root / "report" / "assets" / "data.json").write_text(
    json.dumps({"title": "Fetched from relative JSON"})
)
(root / "site" / "index.html").write_text("<h1 id=siteindex>Site index</h1>")
(root / "site" / "sub" / "note.txt").write_text("note\n")

for n, color in enumerate(
    ("steelblue", "indianred", "seagreen", "goldenrod", "slateblue", "teal"), 1
):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=640x480:d=1",
        "-frames:v",
        "1",
        str(root / "images" / f"frame_{n}.png"),
    )
(root / "images" / "frame_10.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><circle cx="100" cy="100" r="80" fill="orchid"/></svg>'
)
(root / "images" / "broken.png").write_bytes(b"not an image")

ffmpeg(
    "-f",
    "lavfi",
    "-i",
    "testsrc=s=640x360:r=25:d=20",
    "-c:v",
    "libx264",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    str(root / "videos" / "clip.mp4"),
)
ffmpeg(
    "-f",
    "lavfi",
    "-i",
    "testsrc=s=320x240:r=15:d=2",
    "-c:v",
    "libvpx",
    str(root / "videos" / "clip2.webm"),
)
ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(root / "videos" / "tone.wav"))
(root / "videos" / "corrupt.mp4").write_bytes(b"\x00" * 4096)

(root / "data" / "small.csv").write_text(
    "name,score,note\nalpha,10,first\nbeta,9.5,\ngamma,100,last\n"
)
(root / "data" / "quoted.csv").write_text(
    'id,text\r\n1,"a, comma"\r\n2,"say ""hi"""\r\n3,"two\nlines"\r\n4\r\n5,extra,columns,here\r\n'
)
(root / "data" / "semi.csv").write_text("a;b;c\n1;2;3\n")
(root / "data" / "tabs.tsv").write_text("a\tb\n1\t2\n")
(root / "data" / "empty.csv").write_text("")
with open(root / "data" / "events.jsonl", "w") as out:
    for i in range(3000):
        event = {"id": i, "label": ["person", "animal"][i % 2], "score": round(i / 3000, 4)}
        if i % 3 == 0:
            event["box"] = [i, i + 10, 40, 80]
        if i == 7:
            event["late_key"] = "appears later"
        out.write(json.dumps(event) + "\n")
    out.write("not json at all\n")
(root / "data" / "bom.csv").write_bytes("﻿name,value\nx,1\n".encode())
(root / "data" / "<b>evil.csv").write_text(
    "<img src=x onerror='window.__pwned=4'>,b\n<script>window.__pwned=5</script>,2\n"
)
rng = random.Random(7)
with open(root / "data" / "big.csv", "w") as out:
    out.write("clip_id,camera,label,confidence,area,note\n")
    for i in range(400000):
        out.write(
            f'{i},cam{rng.randint(1, 40)},{rng.choice(["person", "animal", "vehicle"])},{rng.random():.4f},{rng.randint(50, 90000)},"note, {i}"\n'
        )

with open(root / "logs" / "big.log", "w") as out:
    for i in range(120000):
        out.write(f"2026-11-05 10:00:{i % 60:02d} INFO step={i} loss={rng.random():.5f}\n")
(root / "logs" / "small.log").write_text("line one\nline two\n")

(root / "src" / "train.py").write_text(
    "import torch\n\n\ndef main():\n    print('train')  # entry\n\n\nmain()\n"
)
(root / "src" / "nms.cpp").write_text("#include <vector>\nint main() { return 0; }\n")
(root / "src" / "CMakeLists.txt").write_text(
    "cmake_minimum_required(VERSION 3.20)\nproject(demo)\n"
)
(root / "src" / "Dockerfile").write_text("FROM python:3.12\nRUN pip install uv\n")
(root / "src" / "config.yaml").write_text("model: yolox\nlr: 0.001\n")
(root / "src" / "weights.bin").write_bytes(bytes(range(256)) * 64)
(root / "config.json").write_text('{"model":"yolox","layers":[1,2,3],"nested":{"a":true}}')
(root / "broken.json").write_text('{"model": oops')
(root / "notes without extension").write_text("plain notes\n")
(root / "a b#c?d%e & café.md").write_text("# Awkward name\n\nOpened fine.\n")
for i in range(1500):
    (root / "many" / f"sample_{i}.txt").write_text(str(i))
office_samples.demo_docx(root / "office" / "review.docx")
office_samples.demo_xlsx(root / "office" / "results.xlsx")
(root / "office" / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(512))
(root / "office" / "broken.xlsx").write_bytes(b"PK\x03\x04 not really a workbook")
(root / ".hidden" / "secret.txt").write_text("PRIVATE\n")
(outside / "external.md").write_text("# External\n\nThrough a symlink.\n")
(root / "linked").symlink_to(outside)
print(root)
