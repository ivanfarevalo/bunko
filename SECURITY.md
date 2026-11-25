# Security policy

## Reporting a vulnerability

Please report security problems privately, through
[GitHub's private vulnerability reporting](https://github.com/ivanfarevalo/shelf/security/advisories/new),
not in a public issue. Include what an attacker could read or do, and the
steps to reproduce it.

You can expect a reply within a week. A fix for a confirmed problem ships in a
patch release, and the advisory credits you unless you'd rather it didn't.

## What counts

shelf's job is to let the right people read one folder and nobody else read
anything. Reports in these areas are especially welcome:

- Reading files outside the served folder, or dotfiles, without `--hidden`.
- Getting past `--allow-user` or `--token`.
- Script injection through file names, Markdown, tables, or search results.
- Writing to the served folder, or anything beyond the cache and config paths.
- Changing someone else's recent files, favorites, or tags, including from
  another website (cross-site request forgery).

Known, documented limits aren't vulnerabilities. Examples include HTML files
you open being able to read other served files, tokens being visible on
untrusted plain-HTTP networks, and other local programs forging Tailscale
headers to a loopback server. See [docs/security.md](docs/security.md) for the
full list.

## Supported versions

Only the latest release gets fixes.
