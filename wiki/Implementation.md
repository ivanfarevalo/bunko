# Implementation

How Bunko is built, and why. The file-by-file layout is in
[docs/development.md](../docs/development.md#layout).

## Shape of the system

```
browser ──HTTP──> ThreadingHTTPServer ──> Handler (server.py)
                                            │
          ┌───────────────┬─────────────────┼──────────────┬──────────────┐
       Access          Root            SearchIndex     ContentSearch    Places
     (access.py)    (paths.py)         (index.py)      (contents.py)  (places.py)
                                                        Thumbnails, Prober (media.py)
                                                        Office (office/)
```

- **One process, standard library only.** `http.server.ThreadingHTTPServer`
  with HTTP/1.1 keep-alive, one thread per connection.
- **The handler only does HTTP.** It routes, checks access, and responds.
  Everything else is a service with no knowledge of HTTP, bound to the handler
  by `make_handler(root, index, **services)`. Tests build servers with just the
  services they need.
- **API endpoints are a table.** `/__bunko/api/<name>` looks the name up in
  `ENDPOINTS` or `PATH_ENDPOINTS`. Path endpoints get the resolved path and its
  `stat` result, so the access check happens in exactly one place.

## URLs

| URL | Serves |
|---|---|
| `/` | The app shell (`index.html`) |
| `/#/<path>?line=&q=&t=&sheet=` | A view in the app. Routing is by the hash, so the server never confuses an app route with a file. |
| `/<path>` | The raw file, as `http.server` would serve it, with range requests and ETags |
| `/__bunko/static/...` | The app's own files |
| `/__bunko/api/...` | JSON: `config`, `stat`, `list`, `search`, `grep`, `places`, `thumb`, `probe`, `office`, `office-part` |

Keeping raw files at their natural paths is what lets served HTML reports load
their own data and images, and lets `curl` keep working.

## Path safety

`Root.resolve` is the single gate. It rejects `..`, null bytes, and encoded
separators, hides dotfiles unless `--hidden` is set, and follows symlinks to
check where they really land. Symlinks may leave the served folder (data often
lives on another disk) but may not reach a dotfile. Listings, the name index,
content search, and places all use the same rules.

## Access

`Access.decide` runs on every request and returns a `Decision`:

- **open:** everyone is allowed.
- **tailscale:** Bunko listens on loopback behind `tailscale serve`, which
  strips any identity headers a client sends and adds the real
  `Tailscale-User-Login`. Logins are matched against `--allow-user` patterns.
  The login also keys each person's places.
- **token:** the token arrives once (link, form, or `Authorization: Bearer`),
  then lives in an `HttpOnly` cookie holding an HMAC of it, named by port. The
  token file is re-read when it changes, so rotation needs no restart.

The only write endpoint, `POST /__bunko/api/places`, requires a custom header
and a JSON content type, and checks `Sec-Fetch-Site`, which together stop
cross-site requests.

## State Bunko keeps

Nothing is written to the served folder. `storage.py` decides where things go:

| What | Where |
|---|---|
| Access token | `~/.config/bunko/token` (mode 0600) |
| Recent, favorites, tags | `~/.config/bunko/state/<hash of root>.json`, a section per user |
| Thumbnails | `~/.cache/bunko/thumbs/`, keyed by path, mtime, and size |
| Service units | `~/.config/systemd/user/bunko-<name>.service` |
| Browser preferences | `localStorage`: theme, sidebar width, open folders, collapsed sections, viewer settings |

## Search

- **Names:** a background walk builds a list of every path (up to two
  million), refreshed when older than two minutes. Searches filter it in
  memory and rank exact and prefix name matches first.
- **Contents:** ripgrep with JSON output when installed, otherwise a Python
  scan over the name index. Both have a time budget and result caps, and every
  hit is re-checked against `Root.resolve`.

## Office files

`bunko/office/` converts Word and Excel with the standard library:

- `common.py` opens the zip and parses XML through a tree builder that strips
  namespaces and refuses any DOCTYPE. Every part is read through a capped
  reader, whatever size the zip claims.
- `word.py` walks the document body into HTML. It resolves styles (headings,
  code, quotes, captions), numbering (Word counts per list definition, so
  lists continue across separate numbering instances), tables with merged
  cells, images, links (only `http`, `https`, and `mailto`), and footnotes.
- `excel.py` streams each sheet with a SAX-style target, keeping only values.
  Shared strings, cell styles, and the 1900 and 1904 date systems decide how
  each value reads.
- `Office` caches the last few results by path, mtime, and size.

The browser sanitizes the Word HTML again with DOMPurify, and loads embedded
images through `office-part`, which serves only raster types from the
document's `word/` folder, under a sandboxing CSP.

## The browser app

- **Native ES modules, no build step.** `static/js/app.js` is the entry point.
  It parses the hash, asks the server for the path's `stat`, and hands a `ctx`
  object to the viewer for that file kind. Viewers live in
  `static/js/viewers/`, grouped by family.
- **The `ctx` contract.** A viewer appends to `ctx.el`, checks `ctx.alive()`
  after every `await` (a newer navigation may have started), and registers
  `ctx.cleanup`, `ctx.mounted`, `ctx.actions` (top-bar buttons), or
  `ctx.reload` as needed. It calls `ctx.rerender()` instead of importing the
  router, which keeps the module graph free of cycles.
- **Large data stays fast.** Text and tables load in chunks with HTTP range
  requests. Tables are virtualized, drawing only the rows on screen. Folders
  draw in batches as you scroll.
- **Live reload** polls `stat` for the open path every 2.5 seconds while the
  tab is visible.
- **Styling** is one stylesheet with design tokens as CSS variables, redefined
  for dark mode.

## Testing

- `tests/test_server.py`, `test_features.py`, and `test_office.py`: about 140
  unit tests against real servers on loopback ports, including hostile inputs
  (path tricks, entity bombs, oversized parts, cross-site writes).
- `tests/e2e.py`: about 200 browser checks in Google Chrome over a generated
  demo tree, with screenshots.
- `tests/office_samples.py` writes valid `.docx` and `.xlsx` files from
  scratch. They were also checked against files written by pandoc,
  LibreOffice, and openpyxl.

## Decisions

| Decision | Why |
|---|---|
| Standard library only | Runs on any server with Python, including ones where nothing can be installed. Ships as one `.pyz`. |
| Hash routing, raw files at natural URLs | `http.server` compatibility: reports, `curl`, and relative links keep working. |
| Read-only | Safe to point at real data; keeps the product focused. |
| Tailscale identity as the recommended mode | Real per-person identity and HTTPS without running an auth system. |
| Places stored on the server | They follow a person between devices, and survive clearing the browser. |
| Office conversion on the server | Keeps the client simple, and the extracted text will feed content search and AI questions. |
| ES modules instead of one script | Clear module boundaries without adding a build step. |
| Own color palette and look | Bunko shouldn't imitate any particular product. |
