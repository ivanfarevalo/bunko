# Roadmap

Where Bunko is going, in the order we expect to get there. The reasons behind
the order are in [Goals and plan](Goals-and-Plan.md), and finished work moves
to [Phases](Phases.md).

## Now: publish

- Publish the repository on GitHub, with CI running.
- First tagged release with the `.pyz` attached.

## Next: a companion for AI agents

AI coding agents write plans, notes, and HTML reports into the folders Bunko
serves. A few small features make Bunko the natural place to read them:

- **`bunko link <path>`** prints the app URL for a file, so an agent can end
  its work with a link instead of a path. A line in an agent's instructions
  (for example `CLAUDE.md`) is enough to use it.
- **A "Changed recently" section** in the sidebar: files modified in the last
  few hours, so what an agent just wrote is one click away.
- **Word and Excel in content search.** The text is already extracted for
  viewing (`bunko/office/`). Content search needs to use it, because ripgrep
  can't see inside the zip.
- **Tag rename and delete in the same in-app box** as favorites, replacing the
  browser's prompt and confirm dialogs.

## Then: ask your files

An **Ask** panel next to search, where you type a question in plain language
("which runs used the 480x864 input, and what did they score?") and get an
answer that cites the files it came from, with each citation opening the file
at that spot.

### How it would work

1. **Retrieve.** Content search already finds matching lines across the tree,
   and name search finds files. A question becomes a few searches, plus the file
   you have open, which narrows thousands of files to a few dozen passages.
2. **Ask a model.** Those passages go to a model as documents, with an
   instruction to answer only from them and cite what it used.
3. **Show the answer with sources.** Each claim links to `file:line`, using the
   same links content search results use today (`#/path?line=N&q=...`).

Retrieval stays on the server. The model only sees the passages Bunko chose,
and the UI shows exactly which ones before anything is sent.

### Providers

The core stays dependency-free. Each provider is an optional extra, configured
on the server and never in the browser:

| Provider | How | Data leaves the machine |
|---|---|---|
| **Claude** | The official `anthropic` Python SDK (`pip install "bunko[claude]"`), Messages API with document content blocks and citations enabled, so answers point to exact passages. The default model would be `claude-opus-5-5`, configurable. | Yes, to Anthropic |
| **OpenAI** | The official `openai` Python SDK | Yes, to OpenAI |
| **Local** | Any OpenAI-compatible endpoint: Ollama, llama.cpp's server, vLLM, LM Studio | No |

A sketch of the configuration (not final):

```bash
ANTHROPIC_API_KEY=... bunko 8100 ~/reports --ask claude
OPENAI_API_KEY=...    bunko 8100 ~/reports --ask openai --ask-model <model>
bunko 8100 ~/reports --ask local --ask-url http://localhost:11434/v1 --ask-model <model>
```

### Images and video

Vision-capable models, whether hosted or local VLMs, can look at what Bunko
already renders:

- Ask about an image or the current video frame ("is the person in this frame
  partly occluded?").
- Ask across a folder of frames, using the thumbnail pipeline to send small
  images instead of originals.
- Sample frames from a video with ffmpeg and ask about the clip.

### Privacy and safety rules

These hold before anything ships:

- **Off by default.** Nothing is sent anywhere unless the server is started
  with `--ask`.
- **Same access rules as everything else.** Retrieval goes through the same
  checks as file requests, so dotfiles and hidden symlink targets never reach a
  model. Only signed-in users can ask.
- **You see what's sent,** passage by passage, before it's sent.
- **Keys stay on the server,** read from the environment and never exposed to
  the browser.
- **Limits:** a cap on passages and tokens per question, and a per-day budget
  for hosted providers.
- **Local-first:** a local endpoint is a first-class option, not an
  afterthought, for folders that must not leave the machine.

## Later: team use

What a team or organization would need beyond today's access modes:

- **Per-folder permissions,** so one server can share some folders with some
  people.
- **Simpler sign-in** for people outside a tailnet, such as single sign-on.
- **PowerPoint (`.pptx`)** as a slide-by-slide view, and older Office formats
  through an optional converter.
- **An audit log** of who opened what, for folders that need one.

## Other ideas

- **Annotation overlays.** Draw boxes from COCO or YOLO label files on images
  and video frames, for reviewing detection datasets and model output.
- **Side-by-side compare** of two images, two videos in sync, or two text files
  as a diff.
- **Jupyter notebooks** rendered with their outputs.
- **Diagrams and math** in Markdown (Mermaid, KaTeX), loaded only when a page
  uses them.
- **Thumbnail cache pruning,** by age or total size.
- **PDF thumbnails** in galleries.
- **Sharing tags** with everyone on the server, alongside personal ones.
- **Smart sections**, such as "modified today" or "every PLAN.md", defined by a
  saved search.

Suggestions and pull requests are welcome. See [docs/development.md](../docs/development.md).
