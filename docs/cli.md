# Command-line reference

```
shelf [PORT] [DIRECTORY] [options]
shelf service install|uninstall|status|logs|restart|list ...
shelf token [--new] [--port N]
```

## Serving

`PORT` and `DIRECTORY` can be given in either order, as positional arguments or
with `-p` and `-d`. A number that isn't also an existing folder is taken as the
port.

| Option | Default | Meaning |
|---|---|---|
| `-p, --port N` | 8000 | Port. Without one, shelf uses 8000 or the next free port. With one, it fails if the port is taken. |
| `-d, --directory DIR` | current folder | Folder to serve |
| `-b, --bind ADDR` | `0.0.0.0` | Address to listen on. `127.0.0.1` keeps it local; a Tailscale IP limits it to the tailnet. |
| `--hidden` | off | Also list and serve dotfiles |
| `--no-thumbnails` | off | Don't run ffmpeg for gallery thumbnails |
| `--cache-dir DIR` | `~/.cache/shelf` | Where thumbnails are cached |
| `-v, --verbose` | off | Log every request to stderr |
| `--version` | | Print the version |

## Access control

See [security.md](security.md). `--allow-user` and `--token` can't be combined.

| Option | Meaning |
|---|---|
| `--allow-user LOGIN` | Allow this Tailscale user. Repeat it for more users; wildcards work (`'*@example.com'`). Requires `-b 127.0.0.1` (or another loopback address) and `tailscale serve` in front. |
| `--token` | Require an access token, creating one if needed |
| `--new-token` | Replace the token, then start. Implies `--token`. |
| `--token-file PATH` | Where the token lives (default `~/.config/shelf/token`) |

The `SHELF_TOKEN` environment variable, when set, overrides the token file.

## `shelf token`

| Command | Does |
|---|---|
| `shelf token` | Print the token, creating it if needed |
| `shelf token --port 8100` | Print a sign-in link (`--host` changes the host name) |
| `shelf token --new` | Replace the token. Running servers pick it up on their next request. |

## `shelf service`

See [deployment.md](deployment.md#as-a-systemd-user-service).

| Command | Does |
|---|---|
| `shelf service install --name NAME -- ARGS...` | Write `~/.config/systemd/user/shelf-NAME.service` to run `shelf ARGS...`, then enable and start it |
| `shelf service install --name NAME --print -- ARGS...` | Print the unit file instead |
| `shelf service list` | Every shelf service and its state |
| `shelf service status --name NAME` | `systemctl --user status` |
| `shelf service logs --name NAME` | Follow the journal |
| `shelf service restart --name NAME` | Restart, for example after upgrading |
| `shelf service uninstall --name NAME` | Stop, disable, and remove the unit |

`--name` defaults to `default`.

## Environment

| Variable | Effect |
|---|---|
| `SHELF_TOKEN` | Use this token instead of the token file |
| `XDG_CONFIG_HOME` | Base for `shelf/token`, `shelf/state/`, and systemd user units (default `~/.config`) |
| `XDG_CACHE_HOME` | Base for `shelf/thumbs` (default `~/.cache`) |

## HTTP endpoints

Raw files are served at their natural paths. The app and its API live under
`/__shelf/`:

| Path | Returns |
|---|---|
| `/` | The app |
| `/<path>` | The raw file, with range requests. A folder redirects to the app. |
| `/__shelf/api/config` | Server info, the signed-in user, and which optional tools are available |
| `/__shelf/api/list?path=` | A folder's entries |
| `/__shelf/api/stat?path=` | Type, size, and modification time |
| `/__shelf/api/search?q=` | Names matching every word |
| `/__shelf/api/grep?q=` | Matching lines inside files |
| `/__shelf/api/thumb?path=` | A JPEG thumbnail, or 404 |
| `/__shelf/api/probe?path=` | Video frame rate, frame count, duration, and codec, or 404 |
| `/__shelf/api/places` | Your recent files, favorites, and tags. A `POST` with a JSON change updates them; it needs the `X-Shelf-Request: 1` header. |
| `/__shelf/logout` | Clears the token cookie |

The API is internal and may change between versions.
