# Deployment

Bunko is a single process with no state beyond a thumbnail cache, so it runs
however you like. Pick the access setup from [security.md](security.md) first;
the examples here use the recommended Tailscale setup.

- [Install](#install)
- [Optional tools](#optional-tools)
- [In the foreground](#in-the-foreground)
- [In tmux](#in-tmux)
- [As a systemd user service](#as-a-systemd-user-service)
- [On machines where you can't install anything](#on-machines-where-you-cant-install-anything)
- [Files Bunko writes](#files-bunko-writes)

## Install

Python 3.8 or later is required, and nothing else.

| Method | Command | Needs |
|---|---|---|
| Try it, no install | `uvx bunko` | [uv](https://docs.astral.sh/uv/) |
| Install the command | `uv tool install bunko`, or `pipx install bunko` | uv or pipx |
| Single file, no package manager | `curl -fsSL https://github.com/ivanfarevalo/bunko/releases/latest/download/install.sh \| sh` | curl |
| Single file, by hand | Download `bunko.pyz` from the [latest release](https://github.com/ivanfarevalo/bunko/releases/latest), run `python3 bunko.pyz` | Nothing |
| From a clone, editable | `uv tool install --editable ./bunko` | uv |

The install script takes `BUNKO_VERSION=0.3.0` to pin a release, and
`BUNKO_INSTALL_DIR` to install somewhere other than `~/.local/bin`. Upgrade
with `uv tool upgrade bunko`, `pipx upgrade bunko`, or by running the script
again.

## Optional tools

Bunko works without any of these, and uses each one when it finds it on the
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
bunko 8100 ~/reports --allow-user you@example.com
```

Stop it with `Ctrl+C`.

## In tmux

This is good for a long-running server you want to glance at, without setting
up a service.

```bash
# a new detached session
tmux new-session -d -s bunko 'bunko 8100 ~/reports --allow-user you@example.com'

# or a window in a session you already use
tmux new-window -d -t main -n bunko 'bunko 8100 ~/reports --allow-user you@example.com'

tmux attach -t bunko     # look at it
tmux kill-session -t bunko
```

With the command passed to tmux this way, the window closes when Bunko exits.
To keep a shell open there instead, create the window first and type the
command into it:

```bash
tmux new-window -d -t main -n bunko
tmux send-keys -t main:bunko 'bunko 8100 ~/reports --allow-user you@example.com' Enter
```

tmux doesn't survive a reboot. For that, use a service.

## As a systemd user service

A user service needs no root. It starts when you log in (or at boot, with
lingering), restarts after a crash, and logs to the journal.

```bash
bunko service install --name reports -- 8100 ~/reports --allow-user you@example.com
```

Everything after `--` is ordinary Bunko arguments. They're checked before
anything is installed, and relative paths become absolute. The command writes
`~/.config/systemd/user/bunko-reports.service`, enables it, and starts it.

```bash
bunko service list                      # every bunko service and whether it's running
bunko service status  --name reports
bunko service logs    --name reports    # follows the journal
bunko service restart --name reports
bunko service uninstall --name reports
```

**Keep it running when you're logged out**, and start it at boot:

```bash
loginctl enable-linger $USER
```

Some systems need `sudo` for that, depending on their policy.

**Upgrading:** install the new version of Bunko, then run
`bunko service restart --name reports`.

**Customizing:** `--print` writes the unit to stdout instead of installing it,
which is handy as a starting point for a system-wide unit or extra systemd
settings:

```bash
bunko service install --name reports --print -- 8100 ~/reports > bunko-reports.service
```

**Tokens:** a service started with `--token` doesn't print its token to the
journal. Get a sign-in link with `bunko token --port 8100`.

**Tailscale addresses at boot:** if you bind to a Tailscale IP and the service
starts before tailscaled has brought the address up, binding fails and systemd
retries every 5 seconds until it works.

## On machines where you can't install anything

Build the zipapp once and copy one file:

```bash
python3 scripts/build_pyz.py     # dist/bunko.pyz, about 130 KB
scp dist/bunko.pyz server:bin/
ssh server 'python3 ~/bin/bunko.pyz 8100 ~/reports'
```

The `.pyz` is the whole app, front-end libraries included, so it works on
machines with no internet access. `python3 bunko.pyz service install ...`
writes a unit that runs the `.pyz` from where it sits.

## Files Bunko writes

Bunko never writes to the folders it serves. It writes only to:

| Path | What | Safe to delete |
|---|---|---|
| `~/.config/bunko/state/*.json` | Recent files, favorites, and tags: one file per served folder, mode 0600 | Yes; you lose those lists |
| `~/.cache/bunko/thumbs/` | Thumbnail cache, keyed by path, size, and modification time | Yes, any time; thumbnails regenerate on demand |
| `~/.config/bunko/token` | The access token, mode 0600, if you use `--token` | Deleting it signs everyone out; a new one is made on next start |
| `~/.config/systemd/user/bunko-*.service` | Units from `bunko service install` | Use `bunko service uninstall` |

`--cache-dir` moves the cache, and `--token-file` moves the token. Both honor
`XDG_CACHE_HOME` and `XDG_CONFIG_HOME`. The thumbnail cache isn't pruned
automatically. Browsing very large image folders adds roughly 10–20 KB per
image, and `rm -rf ~/.cache/bunko/thumbs` clears it.
