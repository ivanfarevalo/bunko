# Security and access control

shelf only ever reads files. The question is **who can read them**. By default
the answer is anyone who can reach the port, exactly as with
`python -m http.server`. This page covers the ways to narrow that, strongest
first.

| Setup | Who gets in | Transport | Effort |
|---|---|---|---|
| [Tailscale Serve + `--allow-user`](#recommended-tailscale-serve-with-allowed-users) | Named people, by Tailscale identity | HTTPS | Two commands |
| [Loopback + SSH forward](#local-only-with-an-ssh-tunnel) | Whoever can SSH to the machine | SSH | One flag, one tunnel |
| [Bind to your Tailscale IP](#bind-to-your-tailscale-address) | Every device on the tailnet | WireGuard | One flag |
| [Access token](#access-token) | Anyone holding the token | Plain HTTP, unless something adds HTTPS | One flag |
| Default | Anyone who can reach the port | Plain HTTP | None |

## Always on

These apply in every mode:

- **The served folder is never changed.** There's no upload, edit, or delete.
  The one write shelf accepts is to your own recent files, favorites, and tags,
  which it keeps in `~/.config/shelf/state/`, outside the served folder. Every
  other `POST`, and every `PUT` and `DELETE`, returns 501.
- **Those writes come only from shelf's own page.** They need a custom
  `X-Shelf-Request` header and a JSON body, which another website can't send
  without a CORS preflight that shelf never allows. Browsers that report
  `Sec-Fetch-Site` must report `same-origin`. Writes go through the same access
  check as reads, and paths must pass the same dotfile and traversal rules.
- **Dotfiles are hidden and refuse to serve**: `.ssh`, `.aws`, `.env`, `.git`,
  and the rest. That includes reaching them through a symlink: a link to
  `~/.ssh` is dropped from listings and returns 404. `--hidden` turns this off.
- **Paths can't escape** with `..`, encoded slashes, or null bytes.
- **Search follows the same rules.** Name and content search apply the same
  checks as file requests, so they can't reveal hidden files either.
- **Markdown is sanitized** before rendering, and the app runs under a strict
  Content Security Policy.
- **Word and Excel files are parsed as untrusted.** XML with a DTD is refused,
  which blocks entity-expansion attacks. Each part of the zip is read with a
  size cap, however small it claims to be. The HTML is built from escaped text,
  allows only `http`, `https`, and `mailto` links, and is sanitized again in
  the browser. Embedded images are served only from the document's `word/`
  folder, only as raster image types, and under a sandboxing CSP.

Symlinks *may* point outside the served folder (to data on another disk, say),
because that's how many people lay out projects. Don't serve a folder whose
symlinks you don't trust.

**Rendered HTML runs as your page.** An HTML file you open in shelf runs its
scripts with the same origin as shelf itself, so it can fetch anything shelf
serves. That's the same as `http.server`, and it's what lets reports load
their own data files. The frame is sandboxed so a page can't navigate away
from or replace the app, but **only open HTML you trust.**

## Recommended: Tailscale Serve with allowed users

[Tailscale Serve](https://tailscale.com/kb/1312/serve) puts an HTTPS address
on your tailnet in front of a local port. When it forwards a request, it adds
the sender's identity in a `Tailscale-User-Login` header, after removing any
copy the client tried to send. shelf checks that header against the users you
allow.

```bash
# 1. shelf listens only on loopback, so nothing reaches it except through Tailscale
shelf 8100 ~/reports -b 127.0.0.1 --allow-user you@example.com

# 2. Tailscale serves it over HTTPS to your tailnet
sudo tailscale serve --bg --https=8100 http://127.0.0.1:8100
```

Then open `https://<machine>.<tailnet>.ts.net:8100/`. The settings panel shows
who you're signed in as.

- **Allow several people** with a repeated flag (`--allow-user a@example.com
  --allow-user b@example.com`) or a wildcard (`--allow-user '*@example.com'`).
  Matching ignores case.
- **Skip `sudo`** after running `sudo tailscale set --operator=$USER` once.
- **Turn it off** with `sudo tailscale serve --https=8100 off`. Run
  `tailscale serve status` to see what's being served.
- **HTTPS has to be enabled** for your tailnet (MagicDNS plus HTTPS
  certificates, in the Tailscale admin console). If `tailscale serve` already
  works for anything else on the machine, it's on.

### Why this is the strongest option

- Every request carries a real person's identity, so access is per person, and
  removing someone from the tailnet removes their access.
- There's no shared secret to leak.
- Traffic is HTTPS end to end, which also enables browser features that
  require a secure page, such as the clipboard API.

### Limits

- **Requests without an identity are refused.** Tailscale adds identity only
  for devices signed in as a person. Requests from
  [tagged devices](https://tailscale.com/kb/1068/tags) and from Funnel (public
  internet) traffic carry no identity, so shelf denies them.
- **Other programs on the same machine** can connect to `127.0.0.1` directly
  and send a forged header. That's why shelf refuses `--allow-user` unless it's
  bound to loopback. On a shared multi-user machine, other local users could
  still do this. Use Tailscale ACLs (below), or run shelf where only you have
  an account.
- **Don't use Funnel.** `tailscale funnel` would put shelf on the public
  internet with no identity attached, so every request would be denied, and
  you don't want it there anyway.

### Narrowing further with Tailscale ACLs

If you administer the tailnet, an ACL or grant can restrict which users can
reach the machine at all. That stacks with `--allow-user`, and it's the right
tool on shared machines. See [Tailscale's ACL docs](https://tailscale.com/kb/1018/acls).

## Local only, with an SSH tunnel

If you already SSH into the machine, keep shelf private to it and tunnel in:

```bash
shelf 8100 ~/reports -b 127.0.0.1          # on the server
ssh -N -L 8100:127.0.0.1:8100 server        # on your laptop
# open http://localhost:8100/
```

Only people who can SSH to the server can reach it. The browser treats
`localhost` as secure, so copy-to-clipboard works natively too.

## Bind to your Tailscale address

```bash
shelf 8100 ~/reports -b 100.101.102.103    # your machine's Tailscale IP (tailscale ip -4)
```

Only devices on your tailnet can connect, and WireGuard encrypts the traffic.
**Everyone on the tailnet** can read the folder, though. That's fine when the
tailnet holds only your devices. On a shared company tailnet, use the
recommended setup instead.

If shelf runs as a service, the Tailscale address may not exist yet when it
starts at boot. The service restarts until it does.

## Access token

```bash
shelf 8100 ~/reports --token
```

On first use, shelf creates a random token in `~/.config/shelf/token`
(readable only by you) and prints a sign-in link:

```
http://myserver:8100/?token=k3X9...
```

1. Open the link once. shelf checks the token, saves a session in an
   `HttpOnly` cookie, and redirects to the clean URL, so the token doesn't
   stay in your address bar or history.
2. From then on the cookie is sent with every request: pages, images, video
   seeking, and HTML reports with their assets.
3. Visitors without it get a sign-in page where they can paste the token.
   They see no files or folder names.

Useful commands:

```bash
shelf token                    # print the token
shelf token --port 8100        # print a sign-in link
shelf token --new              # replace it: every browser must sign in again
shelf 8100 ~/x --new-token     # replace it, then start
SHELF_TOKEN=... shelf --token  # take the token from the environment instead of the file
```

Running servers pick up a replaced token on the next request, so there's no
restart. Scripts can send `Authorization: Bearer <token>` or add `?token=` to
a URL:

```bash
curl -H "Authorization: Bearer $(shelf token)" http://myserver:8100/results/metrics.csv
```

When stdout isn't a terminal, as under systemd, shelf doesn't print the token,
so it stays out of logs. Use `shelf token --port N` to get the link.

### Why it's weaker

- **It's a shared secret.** Anyone holding the link has full read access, and
  there's no per-person identity or revocation short of replacing the token
  for everyone.
- **Plain HTTP shows it to the network.** Anyone who can watch traffic between
  your browser and the server, such as another device on the same Wi-Fi or LAN,
  can read the token and the cookie. Use it over Tailscale (bind to the
  Tailscale IP), over an SSH tunnel, or behind an HTTPS proxy, not across an
  untrusted network.
- **Links travel.** Shell history, chat messages, and screenshots all hold
  copies. Treat the link like a password.

The token is 192 bits of randomness, compared in constant time, and the cookie
holds a value derived from it rather than the token itself. Cookies are named
per port (`shelf_8100`), so several shelf servers on one host don't interfere.

## Reporting a vulnerability

Please report security problems privately through
[GitHub's security advisories](https://github.com/ivanfarevalo/shelf/security/advisories/new),
not in a public issue. See [SECURITY.md](../SECURITY.md).
