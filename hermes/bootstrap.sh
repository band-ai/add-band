#!/usr/bin/env bash
# Connect this machine's Hermes agent to Band, then hand off setup to the add-band skill.
set -euo pipefail

command -v uv >/dev/null || { echo "install uv first: https://docs.astral.sh/uv/"; exit 1; }
command -v hermes >/dev/null || { echo "install hermes first"; exit 1; }

# Get your Band API key: paste it at the prompt (pre-set BAND_API_KEY to skip;
# BAND_USER_API_KEY is honored as an alias).
: "${BAND_API_KEY:=${BAND_USER_API_KEY:-}}"
if [ -z "${BAND_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band API key: ' >/dev/tty
  IFS= read -r -s BAND_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_API_KEY:-}" ] || { echo "Band API key required" >&2; exit 1; }
export BAND_API_KEY

# Install the band platform into the same Python that runs `hermes`.
resolve_hermes_python() {
  local bin target shebang dir p proj
  bin="$(command -v hermes)" || return 1
  for _ in 1 2 3 4; do
    while [ -L "$bin" ]; do
      target="$(readlink "$bin")"
      case "$target" in
        /*) bin="$target" ;;
        *)  bin="$(cd "$(dirname "$bin")" && cd "$(dirname "$target")" && pwd)/$(basename "$target")" ;;
      esac
    done
    # Follow wrapper scripts to the real entrypoint.
    target="$(sed -n 's/^exec "\([^"]*\)".*/\1/p' "$bin" 2>/dev/null | head -1)"
    [ -n "$target" ] && [ "$target" != "$bin" ] && { bin="$target"; continue; }
    break
  done
  # Prefer the interpreter from the console-script shebang.
  shebang="$(sed -n '1s/^#![[:space:]]*//p' "$bin" 2>/dev/null)"; shebang="${shebang%% *}"
  case "$shebang" in */python*) [ -x "$shebang" ] && { printf '%s\n' "$shebang"; return 0; };; esac
  # Fall back to nearby/project venv Pythons.
  dir="$(cd "$(dirname "$bin")" 2>/dev/null && pwd)" || dir=""
  for p in "$dir/python3" "$dir/python"; do [ -x "$p" ] && { printf '%s\n' "$p"; return 0; }; done
  proj="$(hermes --version 2>&1 | sed -n 's/^Project: //p')"
  for p in "$proj/venv/bin/python" "$proj/.venv/bin/python"; do
    [ -x "$p" ] && { printf '%s\n' "$p"; return 0; }
  done
  return 1
}
hermes_python="$(resolve_hermes_python)" \
  || { echo "could not locate the Python that runs hermes; check your install with \`hermes doctor\`" >&2; exit 1; }
BAND_HERMES_REF="${BAND_HERMES_REF:-main}"
# TODO(production release): switch this to a pinned PyPI install
# (`hermes-band-platform==...`) in the PyPI-switch PR. Do not merge that PR
# until the package is published to PyPI and verified installable.
command -v git >/dev/null || { echo "install git first (needed to fetch the band platform from GitHub)"; exit 1; }
uv pip install --python "$hermes_python" "hermes-band-platform @ git+https://github.com/band-ai/hermes-band-platform.git@${BAND_HERMES_REF}"

# Mint the Band agent using the helper bundled with the add-band skill.
skill_dir="$("$hermes_python" -c 'import pathlib, hermes_band_platform; print(pathlib.Path(hermes_band_platform.__path__[0]) / "skills" / "add-band")')"
"$hermes_python" "$skill_dir/scripts/register_agent.py"
unset BAND_API_KEY

# Enable the plugin, then hand off the remaining setup to the add-band skill.
hermes plugins enable band 2>/dev/null && hermes plugins list | grep -qw band \
  || "$hermes_python" -c "from hermes_cli import plugins_cmd as C; s=C._get_enabled_set(); s.add('band'); C._save_enabled_set(s); print('enabled band via config')"
hermes chat -s add-band < /dev/tty
