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

# Install the band platform into the same Python that runs `hermes`. Don't assume a
# `venv/` beside the project dir — layouts vary (.venv, FHS/root, custom dir). Derive
# the interpreter from the `hermes` entrypoint: follow a launcher wrapper to the real
# console script, read its shebang, and fall back to a Python alongside it.
hermes_bin="$(command -v hermes)"
tgt="$(sed -n 's/^exec "\([^"]*\)".*/\1/p' "$hermes_bin" 2>/dev/null | head -1)"
[ -n "$tgt" ] && hermes_bin="$tgt"
hermes_python="$(sed -n '1s/^#![[:space:]]*//p' "$hermes_bin" 2>/dev/null)"; hermes_python="${hermes_python%% *}"
case "$hermes_python" in */python*) ;; *) hermes_python="$(dirname "$hermes_bin")/python3" ;; esac
[ -x "$hermes_python" ] || { echo "could not locate the Python that runs hermes; check your install with \`hermes doctor\`" >&2; exit 1; }
BAND_HERMES_REF="${BAND_HERMES_REF:-main}"
# TODO(production release): switch this to a pinned PyPI install
# (`hermes-band-platform==...`) in the PyPI-switch PR. Do not merge that PR
# until the package is published to PyPI and verified installable.
uv pip install --python "$hermes_python" "hermes-band-platform @ git+https://github.com/band-ai/hermes-band-platform.git@${BAND_HERMES_REF}"

# Mint the Band agent using the helper bundled with the add-band skill.
skill_dir="$("$hermes_python" -c 'import pathlib, hermes_band_platform; print(pathlib.Path(hermes_band_platform.__path__[0]) / "skills" / "add-band")')"
"$hermes_python" "$skill_dir/scripts/register_agent.py"
unset BAND_API_KEY

# Enable the plugin, then hand off the remaining setup to the add-band skill.
# `hermes plugins enable` only sees directory plugins, not entry-point packages
# like band, so it prints a benign "not installed or bundled" on stdout and fails;
# silence both streams and let the config-write fallback enable it. (When the CLI
# learns to enable entry-point plugins, this public path will just start working.)
hermes plugins enable band >/dev/null 2>&1 && hermes plugins list | grep -qw band \
  || "$hermes_python" -c "from hermes_cli import plugins_cmd as C; s=C._get_enabled_set(); s.add('band'); C._save_enabled_set(s); print('enabled band via config')"
# The band plugin namespaces its skills, so the skill resolves as `band:add-band`,
# not the bare `add-band` (plugin skills never enter the flat ~/.hermes/skills tree).
hermes chat -s band:add-band < /dev/tty
