#!/bin/sh
# Install Bunko as a single file: https://github.com/ivanfarevalo/bunko
#
#   curl -fsSL https://github.com/ivanfarevalo/bunko/releases/latest/download/install.sh | sh
#
# Needs only Python 3.8+ and curl. Settings, as environment variables:
#   BUNKO_VERSION       a release such as 0.3.0 (default: the latest)
#   BUNKO_INSTALL_DIR   where the `bunko` command goes (default: ~/.local/bin)
set -eu

repo="https://github.com/ivanfarevalo/bunko"
dir="${BUNKO_INSTALL_DIR:-$HOME/.local/bin}"
if [ -n "${BUNKO_VERSION:-}" ]; then
    url="$repo/releases/download/v${BUNKO_VERSION#v}/bunko.pyz"
else
    url="$repo/releases/latest/download/bunko.pyz"
fi
url="${BUNKO_URL:-$url}" # for testing against a local build

fail() {
    echo "bunko install: $*" >&2
    exit 1
}

command -v python3 >/dev/null 2>&1 || fail "python3 is required (3.8 or later)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' ||
    fail "Python 3.8 or later is required; python3 is $(python3 -V 2>&1)"
command -v curl >/dev/null 2>&1 || fail "curl is required"

mkdir -p "$dir"
temp="$dir/.bunko.download.$$"
trap 'rm -f "$temp"' EXIT
echo "Downloading $url"
curl -fsSL "$url" -o "$temp" || fail "download failed"
chmod +x "$temp"
python3 "$temp" --version >/dev/null 2>&1 || fail "the download doesn't run; nothing was installed"
mv -f "$temp" "$dir/bunko"

echo "Installed $(python3 "$dir/bunko" --version) to $dir/bunko"
case ":$PATH:" in
*":$dir:"*) echo "Run it with: bunko" ;;
*) echo "$dir isn't on your PATH. Add it, or run: $dir/bunko" ;;
esac
