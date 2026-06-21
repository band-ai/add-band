#!/usr/bin/env bash
# Connect this machine's Hermes agent to Band. Bash does only what it's uniquely placed
# to do — install the band plugin (which ships the add-band skill) and mint a Band agent
# from your user key (a script reads the key, never the LLM) — then hands off to the
# skill, which completes plugin setup, wires Band in as a communication channel with
# context isolation, bootstraps the hub, and sends you the agent's first message.
set -euo pipefail

command -v uv >/dev/null || { echo "install uv first: https://docs.astral.sh/uv/"; exit 1; }
command -v hermes >/dev/null || { echo "install hermes first"; exit 1; }

# Get your Band user API key: paste it at the prompt (pre-set BAND_USER_API_KEY to skip).
if [ -z "${BAND_USER_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_USER_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band user API key: ' >/dev/tty
  IFS= read -r -s BAND_USER_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_USER_API_KEY:-}" ] || { echo "Band user API key required" >&2; exit 1; }
export BAND_USER_API_KEY

# Install the band platform (it ships the add-band skill) into the gateway's own Python.
hermes_python="$(hermes --version 2>&1 | sed -n 's/^Project: //p')/venv/bin/python"
[ -x "$hermes_python" ] || { echo "could not find Hermes Python at $hermes_python"; exit 1; }
BAND_HERMES_REF="${BAND_HERMES_REF:-main}"
# TODO(production release): switch this to a pinned PyPI install
# (`hermes-band-platform==...`) in the PyPI-switch PR. Do not merge that PR
# until the package is published to PyPI and verified installable.
uv pip install --python "$hermes_python" "hermes-band-platform @ git+https://github.com/band-ai/hermes-band-platform.git@${BAND_HERMES_REF}"

# Mint the Band agent using the temporary Python helper bundled with the
# add-band skill. Once band-sdk publishes `band.cli.register_agent`, replace this
# with the SDK CLI and remove the bundled helper.
skill_dir="$("$hermes_python" -c 'import pathlib, hermes_band_platform; print(pathlib.Path(hermes_band_platform.__path__[0]) / "skills" / "add-band")')"
"$hermes_python" "$skill_dir/scripts/register_agent.py"
unset BAND_USER_API_KEY

# Enable the plugin, then hand off to the agent: the add-band skill restarts the gateway,
# wires Band in as a comms channel with context isolation, bootstraps the hub, and sends
# you the agent's first message — the steps that need agent smarts, not bash.
hermes plugins enable band 2>/dev/null && hermes plugins list | grep -qw band \
  || "$hermes_python" -c "from hermes_cli import plugins_cmd as C; s=C._get_enabled_set(); s.add('band'); C._save_enabled_set(s); print('enabled band via config')"
hermes chat -s add-band < /dev/tty
