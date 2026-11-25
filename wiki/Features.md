# Features

Everything Bunko does today, by area. The user-facing details, with
screenshots, are in [docs/features.md](../docs/features.md).

## Viewing files

| File types | Viewer | Since |
|---|---|---|
| Markdown | GitHub-flavored, sanitized, with highlighted code, copy buttons, working relative links and images, folded front matter, and an optional outline | 0.1, outline 0.2 |
| HTML | The page itself in a sandboxed frame, with its scripts, styles, and relative assets working, and links inside it tracked in the address bar | 0.1 |
| Images | Fitted, click to zoom, arrow keys to step through the folder | 0.1 |
| Video and audio | The browser's player, plus frame stepping, frame numbers, speed control, and links to an exact moment | 0.1, review tools 0.2 |
| CSV, TSV | A virtualized table that loads in pieces, sorts, and filters, with the delimiter detected | 0.1 |
| JSONL | The same table, with columns from the keys, or as text | 0.2 |
| Word (`.docx`) | A page with headings, lists, tables, images, links, footnotes, and code blocks, with the outline | 0.3 |
| Excel (`.xlsx`) | The table viewer, a tab per sheet, Excel's row numbers, and formatted dates and percentages | 0.3 |
| JSON | Pretty-printed and highlighted | 0.1 |
| PDF | The browser's PDF viewer | 0.1 |
| Code, logs, text | Line numbers, highlighting, and loading in steps for large files | 0.1 |
| Anything else | Sniffed: text shows as text, and binaries get a download card that says why | 0.1 |

## Finding files

- **Name search** (`Ctrl+K`) over an in-memory index of every path, with
  ranked results. *0.1*
- **Content search** (`Ctrl+Shift+F`) inside files, using ripgrep or a Python
  fallback. Results open at the matching line, highlighted. *0.2*
- **Folder tree** with lazy loading and "show more" for huge folders, and
  **galleries** for folders of images and video, with ffmpeg thumbnails. *0.1,
  thumbnails 0.2*

## Personal places

- **Recent** files, **Favorites** with optional nicknames, and **tags**, each
  tag with its own sidebar section. Stored on the server, per Tailscale user.
  *0.3*
- Collapsible sections with a sticky heading for the one you're in. *0.3*

## Living with changing files

- **Live reload** of the open file and folder while the tab is visible, with a
  manual reload for large files. *0.1*
- **Links to everything:** each view has a URL, including a line, a search
  term, a sheet, or a moment in a video. *0.1 to 0.3*

## Access and running

- **Access modes:** open (the default, like `http.server`), Tailscale identity
  behind `tailscale serve` (recommended), or an access token. *0.2*
- **Dotfile protection,** including through symlinks, and refusal of path
  tricks. *0.1*
- **Runs anywhere:** in the foreground, in tmux, as a systemd user service
  (`bunko service`), or as a single `.pyz` file. *0.1, service 0.2*

## Interface

- Resizable sidebar, light and dark themes, a phone layout with a drawer,
  keyboard shortcuts, and a Settings panel. *0.1 to 0.2*
