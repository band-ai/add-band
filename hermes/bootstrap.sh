#!/usr/bin/env bash
# Connect this machine's Hermes agent to Band. Bash does only what it's uniquely placed
# to do — install the band plugin (which ships the add-band skill) and mint a Band agent
# from your Band API key (a script reads the key, never the LLM) — then hands off to the
# skill, which completes plugin setup, wires Band in as a communication channel with
# context isolation, bootstraps the hub, and sends you the agent's first message.
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

# Find the gateway venv's Python (NOT HERMES_HOME — that's the config/data dir, a
# separate location from the code checkout where venv/bin/python lives). This mirrors
# how Hermes's own installer + uninstaller locate the install: the installer writes
# the on-PATH `hermes` as a shim that `exec`s "<root>/venv/bin/hermes", and the
# uninstaller's get_project_root() treats <root>/venv as the install to remove.
#   installer (setup_path):         https://github.com/NousResearch/hermes-agent/blob/main/scripts/install.sh
#   uninstaller (get_project_root): https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/uninstall.py
# Discovery, most-robust first: (1) follow the `hermes` launcher on PATH to the venv
# hermes it runs (older installs symlink straight to it) and take its sibling python;
# (2) last-ditch, scrape the start-anchored `Project:` line `hermes --version` prints
# (the code root) and append venv/bin/python, so installs where only that still works
# don't regress.
hermes_python=""
hermes_launcher="$(command -v hermes)"
# Resolve symlinks one level at a time (portable; no GNU `readlink -f`).
while [ -L "$hermes_launcher" ]; do
  hermes_target="$(readlink "$hermes_launcher")"
  case "$hermes_target" in
    /*) hermes_launcher="$hermes_target" ;;
    *)  hermes_launcher="$(dirname "$hermes_launcher")/$hermes_target" ;;
  esac
done
# A symlink resolves straight onto <root>/venv/bin/hermes; a shim is a script that
# execs it — pull the quoted exec target out of the file in that case.
hermes_venv_bin=""
case "$hermes_launcher" in
  */venv/bin/hermes) hermes_venv_bin="$hermes_launcher" ;;
  *) hermes_venv_bin="$(sed -n 's/^exec "\([^"]*\)".*/\1/p' "$hermes_launcher" 2>/dev/null | head -n1)" ;;
esac
case "$hermes_venv_bin" in
  */venv/bin/hermes) hermes_python="$(dirname "$hermes_venv_bin")/python" ;;
esac
# Last-ditch fallback: the start-anchored `Project:` line from `hermes --version`.
[ -x "${hermes_python:-}" ] \
  || hermes_python="$(hermes --version 2>&1 | sed -n 's/^Project: //p')/venv/bin/python"
[ -x "$hermes_python" ] || { echo "could not find Hermes Python at $hermes_python"; exit 1; }
BAND_HERMES_REF="${BAND_HERMES_REF:-main}"
# TODO(production release): switch this to a pinned PyPI install
# (`hermes-band-platform==...`) in the PyPI-switch PR. Do not merge that PR
# until the package is published to PyPI and verified installable.
uv pip install --python "$hermes_python" "hermes-band-platform @ git+https://github.com/band-ai/hermes-band-platform.git@${BAND_HERMES_REF}"

# Mint the Band agent using the temporary Python helper bundled with the
# add-band skill. Once band-sdk publishes `band.cli.register_agent`, replace this
# with the SDK CLI and remove the bundled helper. The SDK CLI must preserve the
# helper's browser-like registration headers (User-Agent, Accept,
# Accept-Language), otherwise app.band.ai can Cloudflare-1010 sparse script
# fingerprints even when the key is valid.
skill_dir="$("$hermes_python" -c 'import pathlib, hermes_band_platform; print(pathlib.Path(hermes_band_platform.__path__[0]) / "skills" / "add-band")')"
"$hermes_python" "$skill_dir/scripts/register_agent.py"
unset BAND_API_KEY

# Enable the plugin, then hand off to the agent: the add-band skill restarts the gateway,
# wires Band in as a comms channel with context isolation, bootstraps the hub, and sends
# you the agent's first message — the steps that need agent smarts, not bash.
hermes plugins enable band 2>/dev/null && hermes plugins list | grep -qw band \
  || "$hermes_python" -c "from hermes_cli import plugins_cmd as C; s=C._get_enabled_set(); s.add('band'); C._save_enabled_set(s); print('enabled band via config')"
hermes chat -s add-band < /dev/tty
