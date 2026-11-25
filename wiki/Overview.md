# Overview

## What Bunko is

Bunko is a self-hosted, read-only file server that renders the files it
serves. Run one command in a folder and open the address it prints: the folder
tree and search sit in a sidebar, and whatever you open shows in the main pane,
properly rendered. That includes Markdown, HTML reports, Word documents, Excel
workbooks, CSV and JSONL tables, images, video, PDFs, code, and logs.

It began as a replacement for `python -m http.server`, and it keeps that
contract: files stay at their natural URLs, so `curl`, `wget`, and links inside
served HTML keep working. It needs only Python, with no packages to install,
and it never writes to the folder it serves.

## Who it's for

People who need to *read* files that live somewhere else, usually a remote
machine:

- **Engineers and researchers on remote servers.** Experiment results, plots,
  logs, HTML reports, video clips, and large tables, read from a browser,
  without copying anything back.
- **People working with AI coding agents.** Agents like Claude Code write
  plans, notes, context files, and HTML reports. Bunko shows them as they're
  written, privately, on your own machine, rather than on a hosted page.
- **Small teams sharing a server.** One read-only place for documents, with
  search, per-person favorites and tags, and access tied to identity
  (Tailscale) or a token.

## What it deliberately isn't

- **Not an editor.** Bunko is read-only. That makes it safe to point at real
  data, and easy to approve for a team. Editing would turn it into a wiki or a
  CMS, which is a different and crowded product.
- **Not a sync or upload tool.** It reads files where they already are. There's
  no import step and no database.
- **Not a hosted service.** It runs on your machine or server, and nothing
  leaves it unless you set up a model provider for the planned AI features.

## Principles

1. **One command, no dependencies.** Standard-library Python 3.8+, and a
   front end with no build step. A single `.pyz` file runs anywhere Python does.
2. **Read-only and private by default.** Dotfiles stay hidden, paths can't
   escape, and every request passes one access check.
3. **Render things properly.** Each file type gets a viewer built for it, not
   a generic preview.
4. **Fast on large data.** Folders with thousands of files, tables with
   hundreds of thousands of rows, and logs over a gigabyte stay responsive.
5. **Files are untrusted.** Anything rendered is sanitized, and anything parsed
   is capped.
