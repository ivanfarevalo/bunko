# Development

```bash
git clone https://github.com/ivanfarevalo/shelf
cd shelf
python3 -m shelf 8100 .            # run from the checkout, no install needed
uv tool install --editable .       # or put an editable `shelf` on your PATH
```

## Layout

```
shelf/
  cli.py        command line, `shelf service`, `shelf token`; builds the server
  server.py     HTTP handler: routing, files with range requests, folder listings, name index
  access.py     open, token, and Tailscale-identity access control; sign-in pages
  contents.py   search inside files (ripgrep, or a Python fallback)
  media.py      thumbnails (ffmpeg) and video facts (ffprobe)
  places.py     recent files, favorites and tags, stored per user in ~/.config/shelf/state
  office.py     Word and Excel files, converted to HTML and table rows
  service.py    systemd user units
  static/       the front end: index.html, app.js, style.css, theme.js
    vendor/     marked, DOMPurify, highlight.js, with their licenses
scripts/build_pyz.py   builds dist/shelf.pyz
tests/                 unit tests, a demo-tree generator, browser tests
```

The rules that keep shelf easy to run:

- **Standard library only** at runtime, and Python 3.8+. Optional tools
  (ffmpeg, ripgrep) are found on PATH and never required.
- **No build step for the front end.** It's plain JavaScript and CSS, with
  third-party libraries vendored so shelf works offline.
- **The served folder is read-only.** shelf writes only to its own state,
  cache, and config, never to the folder it serves.
- **One access check.** Every path, including search results, goes through
  `Root.resolve`, which enforces the dotfile and traversal rules.

## Tests

```bash
python3 -m unittest discover -s tests       # about 140 tests, a few seconds
```

The unit tests start real servers on loopback ports and cover path traversal,
dotfiles through symlinks, range requests, every access mode, thumbnails and
probing (when ffmpeg is installed), content search with both engines, Word
and Excel conversion (including damaged and hostile files), and service units.
`tests/office_samples.py` writes the `.docx` and `.xlsx` fixtures from scratch,
so the tests don't need Office or any packages.

The browser tests drive Google Chrome through every viewer, the search modes,
the video tools, sign-in flows, and the phone layout, and save screenshots:

```bash
python3 tests/make_demo.py /tmp/shelf-demo            # needs ffmpeg
uv run --no-project --with playwright python tests/e2e.py /tmp/shelf-demo /tmp/shelf-shots
```

They use Google Chrome rather than Playwright's bundled Chromium, because
Chromium can't play H.264 video. Set `SHELF_E2E_CHROME=/path/to/chrome` to
choose a binary, or run `playwright install chrome`.

## Updating the vendored libraries

Versions are listed in `shelf/static/vendor/VERSIONS.txt`.

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
checks for Markdown and tables.

## Releasing

1. Bump `__version__` in `shelf/__init__.py` and add an entry to `CHANGELOG.md`.
2. Run both test suites.
3. `python3 scripts/build_pyz.py`, and attach `dist/shelf.pyz` to the GitHub release.
4. Tag `vX.Y.Z`.

## Contributing

Issues and pull requests are welcome. For a change in behavior, please open an
issue first to talk it over. Keep pull requests focused, add tests for what
they change, and keep the runtime dependency-free.
