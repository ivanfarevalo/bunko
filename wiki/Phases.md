# Phases

The project's history, from the first question to now. Each phase lists what
it set out to do, what it delivered, and what it taught us. Release notes for
users are in the [changelog](../CHANGELOG.md).

The project was called "shelf" until 2026-11-24, when it was renamed Bunko,
because "shelf" was already taken by several projects.

## Phase 0: Research (early November 2026)

**Question.** `python -m http.server` is the quickest way to look at files on
a remote machine, but it only lists them. Is there an open-source server that
renders them nicely, with a sidebar for the folder tree and search?

**Findings.** Popular file servers and browsers focus on managing files:
uploading, sharing, permissions. They render few formats, or need a database,
Docker, or a build to run. None was a single dependency-free command that
renders Markdown, HTML reports, tables, and video in place.

**Decision.** Build one, with `http.server`'s simplicity as the constraint:
standard-library Python and no front-end build step.

## Phase 1: A better `http.server` (0.1.0)

**Delivered.**

- The app shell: a sidebar with the folder tree and name search, and a main
  pane with a viewer for each file type (Markdown, HTML, images, video, audio,
  CSV and TSV tables, JSON, PDF, code, and text).
- Raw files at their natural URLs, with range requests, so video seeks and
  served HTML reports keep working.
- Dotfile protection, including through symlinks, and live reload.
- A single-file `.pyz` build for machines where nothing can be installed.

**Learned.** Large real-world folders and files drive the design: tables and
text needed chunked loading and virtualization, and folders needed batched
drawing, to stay fast.

## Phase 2: Safe to share (0.2.0, 2026-11-11)

**Why.** Binding to a Tailscale address made files visible to everyone on a
shared tailnet, so access control came first.

**Delivered.**

- Access modes: Tailscale identity behind `tailscale serve` (recommended), and
  access tokens (the weaker option), plus a warning when a server is open to
  the network.
- Content search with ripgrep or a Python fallback, opening results at the
  matching line.
- Video review tools: frame stepping, frame numbers from ffprobe, speed, and
  links to an exact moment.
- ffmpeg thumbnails, JSONL tables, the Markdown outline, and the Settings
  panel.
- `bunko service` for systemd user services, alongside running in tmux.
- Documentation for users: features, security, deployment, and the CLI.

**Learned.** Without care, a test run writes to the real config folder: tests
now isolate `XDG_CONFIG_HOME` and `XDG_CACHE_HOME`.

## Phase 3: A place to work from (0.3.0, 2026-11-11 to 2026-11-13)

**Delivered.**

- Recent files, favorites, and tags in the sidebar, stored on the server per
  Tailscale user, through Bunko's only write endpoint.
- Collapsible sections, with only the current section's heading sticky.
- Nicknames for favorites, edited in a small box rather than a browser prompt.
- Word and Excel files, converted with the standard library.

**Learned.** Hand-written test files can pass every unit test and still be
invalid Office files. Converting real files written by pandoc, LibreOffice,
and openpyxl found four bugs (list numbering across numbering instances, code
styles, doubled footnote superscripts, repeated bookmark ids), all now covered
by tests.

## Phase 4: A maintained project (in progress, from 2026-11-24)

**Why.** Bunko is meant to be an open-source project others can use and
contribute to. That needs a repository, a development setup, and code that is
easy to read and change.

**Delivered so far.**

- Its own Git repository.
- uv for the environment, ruff for Python, Biome for JavaScript and CSS, and
  pre-commit to run them, also in CI.
- A code review against the design practices in
  [docs/development.md](../docs/development.md#practices):
  - `server.py` split into `paths.py` (path rules), `index.py` (name search),
    and the HTTP layer.
  - API endpoints and places operations dispatched from tables instead of long
    `if` chains.
  - Repeated config-directory and private-file code moved into `storage.py`.
  - `office.py` split into a package: safe reading, Word, and Excel.
  - The 2,700-line `app.js` split into 22 ES modules, with no import cycles.
  - Broad `except Exception` handlers narrowed to the errors that can happen.
- A positioning that doesn't lean on any other product: its own palette and
  description.
- A README that leads with how to launch it, this wiki, and development docs.
- The new name, **Bunko** (文庫, "a library" in Japanese): the command,
  package, config folders, URLs, and docs.

- Published at github.com/ivanfarevalo/bunko on 2026-11-25, with CI on Linux
  and macOS (Python 3.8 to 3.13) and browser tests. Getting CI green found a
  macOS-only test assumption, a hover race in the browser tests, and a newer
  Chrome logging the blocked test injections; DOMPurify was updated to 3.5.0.
- Listening on 127.0.0.1 by default, and a release workflow: PyPI by trusted
  publishing, a GitHub release with `bunko.pyz`, and an `install.sh` one-liner.

**Still open.** The first tagged release.

## What comes next

See the [Roadmap](Roadmap.md) for the next phases: a companion for AI agents,
"ask your files", and team use.
