# Development

- [Set up](#set-up)
- [Layout](#layout)
- [Tools](#tools)
- [Tests](#tests)
- [Practices](#practices)
- [Updating the vendored libraries](#updating-the-vendored-libraries)
- [Releasing](#releasing)

## Set up

You need [uv](https://docs.astral.sh/uv/) and Git. Node.js is optional: the
JavaScript and CSS checks fetch it themselves through pre-commit.

```bash
git clone https://github.com/ivanfarevalo/bunko
cd bunko
uv sync                          # .venv with Python 3.12 and the dev tools
uv run pre-commit install        # run the checks on every commit
uv run playwright install chrome # only for the browser tests
```

Run Bunko from the checkout, against any folder:

```bash
uv run bunko 8100 ~/some/folder
```

Front-end files are read from disk on every request, so editing
`bunko/static/` only needs a browser reload. Python changes need a restart.

## Layout

```
bunko/
  cli.py            command line, `bunko token`; sets up and starts the server
  server.py         HTTP: routing, the API, files with range requests
  paths.py          the served folder and which paths may be read
  index.py          the in-memory name index for search
  contents.py       search inside files (ripgrep, or a Python fallback)
  access.py         open, token, and Tailscale-identity access; sign-in pages
  places.py         recent files, favorites, and tags, per user
  media.py          thumbnails (ffmpeg) and video facts (ffprobe)
  office/           Word and Excel, converted for the viewer
    common.py       reading the zip and XML safely
    word.py         .docx to HTML
    excel.py        .xlsx to rows
  registry.py       records of running servers, for `bunko link`
  service.py        `bunko service`: systemd user units
  storage.py        where bunko keeps its own config, state, and cache
  static/
    index.html      the page shell
    style.css       all styles, with light and dark themes as CSS variables
    theme.js        applies the saved theme before first paint
    js/             the app, as native ES modules (no build step)
      app.js        entry point: routing, rendering, live reload, shortcuts
      viewers/      one module per family of file types
    vendor/         marked, DOMPurify, highlight.js, with their licenses
scripts/build_pyz.py    builds dist/bunko.pyz
tests/                  unit tests, fixtures, a demo-tree generator, browser tests
wiki/                   project notes: goals, phases, implementation, roadmap
```

## Tools

| Tool | Checks | Run it |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | The environment, from `pyproject.toml` and `uv.lock` | `uv sync` |
| [ruff](https://docs.astral.sh/ruff/) | Python lint and formatting (config in `pyproject.toml`) | `uv run ruff check --fix .` and `uv run ruff format .` |
| [Biome](https://biomejs.dev/) | JavaScript and CSS lint and formatting (config in `biome.json`) | `npx @biomejs/biome check --write` |
| [pre-commit](https://pre-commit.com/) | All of the above, plus whitespace, YAML and TOML syntax, merge markers, and large files, on every commit | `uv run pre-commit run --all-files` |

The dev tools are pinned in `pyproject.toml` (`[dependency-groups]`) and
`.pre-commit-config.yaml`. They need Python 3.10 or later; Bunko itself still
runs on 3.8.

CI runs pre-commit, the unit tests on Python 3.8 to 3.13 on Linux and macOS,
and the browser tests.

## Tests

```bash
uv run python -m unittest discover -s tests     # unit tests, about 10 seconds
```

The unit tests start real servers on loopback ports. They cover path
traversal, dotfiles through symlinks, range requests, every access mode,
thumbnails and probing (when ffmpeg is installed), content search with both
engines, Word and Excel conversion (including damaged and hostile files), and
service units. `tests/office_samples.py` writes the `.docx` and `.xlsx`
fixtures from scratch, so no Office software is needed.

To check the oldest supported Python:

```bash
uv run --python 3.8 --no-project python -m unittest discover -s tests
```

The browser tests drive Google Chrome through every viewer, the search modes,
the video tools, places, sign-in flows, and the phone layout, and save
screenshots:

```bash
python3 tests/make_demo.py /tmp/bunko-demo        # needs ffmpeg
uv run python tests/e2e.py /tmp/bunko-demo /tmp/bunko-shots
```

They use Google Chrome rather than Playwright's bundled Chromium, because
Chromium can't play H.264 video. Set `BUNKO_E2E_CHROME=/path/to/chrome` to use
a specific binary.

## Practices

**Runtime rules.** These keep Bunko a single command anyone can run:

- Standard library only, Python 3.8 and later. Optional tools (ffmpeg,
  ripgrep) are found on `PATH` and never required.
- No front-end build step. Plain JavaScript modules and CSS; third-party
  libraries are vendored so Bunko works offline.
- The served folder is never written to. Bunko writes only its own config,
  state, and cache (see `storage.py`).
- One access check. Every path, including search results and places, goes
  through `Root.resolve`.
- Files are untrusted. Rendered Markdown and Word HTML are sanitized, and
  Office files are parsed with size caps and without DTDs.

**Design.** Bunko is a small server plus a browser app. It's written mostly
as modules of functions, with classes where there's state to hold: the index,
the stores, the access policy. In practice:

- One responsibility per module. The HTTP layer only routes and responds.
  Path rules, the index, search, access, places, and file conversion each live
  in their own module and know nothing about HTTP.
- Dependencies come in from outside. `make_handler` binds the services a
  server uses, so tests build servers with exactly the parts they need.
  Viewers get what they need through their `ctx` instead of reaching for the
  app module.
- Tables over long `if` chains. API endpoints, places operations, and viewers
  are looked up by name, so adding one doesn't touch the others.
- Say it once. Shared rules live in one place: dotfile and symlink rules in
  `paths.py`, XDG directories and private writes in `storage.py`, file kinds
  in `kinds.js`.
- Short functions. Split out a helper when a function starts doing two things.

**Comments and docstrings.**

- Public modules, classes, and functions get a short docstring saying what
  they do. Private helpers get one only when the name isn't enough.
- Comments explain *why*: a constraint, a browser quirk, a security reason.
  Not *what* the next line does, and not how the code got this way. History
  belongs in Git, the changelog, and the [wiki](../wiki/Home.md).
- No commented-out code.

**Tests.** Every change in behavior comes with a test: a unit test for the
server, a browser check for the UI. Security rules get tests that try to break
them.

**Commits and pull requests.** Small, focused commits, with a message that
says what changed and why. Keep `main` passing. Open a pull request for
anything beyond a small fix, and an issue first for a change in behavior.
Update `CHANGELOG.md` for anything a user would notice.

## Updating the vendored libraries

Versions are listed in `bunko/static/vendor/VERSIONS.txt`.

```bash
npm pack marked@<v> dompurify@<v> @highlightjs/cdn-assets@<v>
# then copy:
#   marked:       lib/marked.umd.js         -> vendor/marked.js
#   DOMPurify:    dist/purify.min.js        -> vendor/purify.js
#   highlight.js: highlight.min.js + languages/cmake.min.js + languages/dockerfile.min.js
#                                           -> vendor/highlight.js (concatenated)
# strip sourceMappingURL lines, and update VERSIONS.txt and LICENSES/
```

Run both test suites afterwards. The browser tests include script-injection
checks for Markdown, Word documents, and tables.

## Releasing

Releases are built and published by `.github/workflows/release.yml` when a
version tag is pushed:

1. Bump `__version__` in `bunko/__init__.py`, and make sure `CHANGELOG.md` has
   a `## X.Y.Z` section. It becomes the release notes.
2. Run pre-commit and both test suites, and let CI pass on `main`.
3. Tag and push:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

The workflow checks the tag matches `__version__`, builds the wheel, the
sdist, and `bunko.pyz`, and smoke-tests them. It publishes to PyPI, then
creates the GitHub release with `bunko.pyz`, `install.sh`, and the packages
attached.

**PyPI publishing uses trusted publishing,** so no API token is stored. It
was set up once on PyPI, as a publisher for the project `bunko`: owner
`ivanfarevalo`, repository `bunko`, workflow `release.yml`, environment `pypi`.
