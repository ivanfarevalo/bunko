# Deployment

shelf is a single process with no state beyond a thumbnail cache, so it runs
however you like. Pick the access setup from [security.md](security.md) first;
the examples here use the recommended Tailscale setup.

- [Install](#install)
- [Optional tools](#optional-tools)
- [In the foreground](#in-the-foreground)
- [In tmux](#in-tmux)
- [As a systemd user service](#as-a-systemd-user-service)
- [On machines where you can't install anything](#on-machines-where-you-cant-install-anything)
- [Files shelf writes](#files-shelf-writes)

## Install

```bash
uv tool install git+https://github.com/ivanfarevalo/shelf
# or
pipx install git+https://github.com/ivanfarevalo/shelf
# or, from a clone, editable while you hack on it
uv tool install --editable ./shelf
```

All three put a `shelf` command on your PATH. Python 3.8 or later is required.

## Optional tools

shelf works without any of these, and uses each one when it finds it on the
server's PATH:

| Tool | Adds | Without it |
|---|---|---|
| `ffmpeg` | Thumbnails for large images and video posters in galleries | Galleries load full images and show icons for videos |
| `ffprobe` (ships with ffmpeg) | Exact frame rate, frame count, and codec for the video tools | The frame rate is estimated in the browser during playback |
| `rg` ([ripgrep](https://github.com/BurntSushi/ripgrep)) | Fast content search; searches files up to 64 MB | A slower Python search over files up to 5 MB |

```bash
sudo apt install ffmpeg ripgrep     # Debian, Ubuntu
brew install ffmpeg ripgrep         # macOS
```

## In the foreground

```bash
shelf 8100 ~/reports -b 127.0.0.1 --allow-user you@example.com
```

Stop it with `Ctrl+C`.

## In tmux

This is good for a long-running server you want to glance at, without setting
up a service.

```bash
# a new detached session
tmux new-session -d -s shelf 'shelf 8100 ~/reports -b 127.0.0.1 --allow-user you@example.com'

# or a window in a session you already use
tmux new-window -d -t main -n shelf 'shelf 8100 ~/reports -b 127.0.0.1 --allow-user you@example.com'

tmux attach -t shelf     # look at it
tmux kill-session -t shelf
```

With the command passed to tmux this way, the window closes when shelf exits.
To keep a shell open there instead, create the window first and type the
command into it:

```bash
tmux new-window -d -t main -n shelf
tmux send-keys -t main:shelf 'shelf 8100 ~/reports -b 127.0.0.1 --allow-user you@example.com' Enter
```

tmux doesn't survive a reboot. For that, use a service.

## As a systemd user service

A user service needs no root. It starts when you log in (or at boot, with
lingering), restarts after a crash, and logs to the journal.

```bash
shelf service install --name reports -- 8100 ~/reports -b 127.0.0.1 --allow-user you@example.com
```

Everything after `--` is ordinary shelf arguments. They're checked before
anything is installed, and relative paths become absolute. The command writes
`~/.config/systemd/user/shelf-reports.service`, enables it, and starts it.

```bash
shelf service list                      # every shelf service and whether it's running
shelf service status  --name reports
shelf service logs    --name reports    # follows the journal
shelf service restart --name reports
shelf service uninstall --name reports
```

**Keep it running when you're logged out**, and start it at boot:

```bash
loginctl enable-linger $USER
```

Some systems need `sudo` for that, depending on their policy.

**Upgrading:** install the new version of shelf, then run
`shelf service restart --name reports`.

**Customizing:** `--print` writes the unit to stdout instead of installing it,
which is handy as a starting point for a system-wide unit or extra systemd
settings:

```bash
shelf service install --name reports --print -- 8100 ~/reports > shelf-reports.service
```

**Tokens:** a service started with `--token` doesn't print its token to the
journal. Get a sign-in link with `shelf token --port 8100`.

**Tailscale addresses at boot:** if you bind to a Tailscale IP and the service
starts before tailscaled has brought the address up, binding fails and systemd
retries every 5 seconds until it works.

## On machines where you can't install anything

Build the zipapp once and copy one file:

```bash
python3 scripts/build_pyz.py     # dist/shelf.pyz, about 130 KB
scp dist/shelf.pyz server:bin/
ssh server 'python3 ~/bin/shelf.pyz 8100 ~/reports -b 127.0.0.1'
```

The `.pyz` is the whole app, front-end libraries included, so it works on
machines with no internet access. `python3 shelf.pyz service install ...`
writes a unit that runs the `.pyz` from where it sits.

## Files shelf writes

shelf never writes to the folders it serves. It writes only to:

| Path | What | Safe to delete |
|---|---|---|
| `~/.config/shelf/state/*.json` | Recent files, favorites, and tags: one file per served folder, mode 0600 | Yes; you lose those lists |
| `~/.cache/shelf/thumbs/` | Thumbnail cache, keyed by path, size, and modification time | Yes, any time; thumbnails regenerate on demand |
| `~/.config/shelf/token` | The access token, mode 0600, if you use `--token` | Deleting it signs everyone out; a new one is made on next start |
| `~/.config/systemd/user/shelf-*.service` | Units from `shelf service install` | Use `shelf service uninstall` |

`--cache-dir` moves the cache, and `--token-file` moves the token. Both honor
`XDG_CACHE_HOME` and `XDG_CONFIG_HOME`. The thumbnail cache isn't pruned
automatically. Browsing very large image folders adds roughly 10–20 KB per
image, and `rm -rf ~/.cache/shelf/thumbs` clears it.
