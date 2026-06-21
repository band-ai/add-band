#!/usr/bin/env bash
# Connect this machine's Hermes agent to Band. Bash does only what it's uniquely placed
# to do — install the band plugin (which ships the add-band skill) and mint a Band agent
# from your user key (a script reads the key, never the LLM) — then hands off to the
# skill, which completes plugin setup, wires Band in as a communication channel with
# context isolation, bootstraps the hub, and sends you the agent's first message.
set -euo pipefail

export BAND_USER_API_KEY={{BAND_USER_API_KEY}}   # the web app fills this in
command -v uv >/dev/null || { echo "install uv first: https://docs.astral.sh/uv/"; exit 1; }
command -v hermes >/dev/null || { echo "install hermes first"; exit 1; }

# Install the band platform (it ships the add-band skill) into the gateway's own Python.
hermes_python="$(hermes --version 2>&1 | sed -n 's/^Project: //p')/venv/bin/python"
[ -x "$hermes_python" ] || { echo "could not find Hermes Python at $hermes_python"; exit 1; }
uv pip install --python "$hermes_python" hermes-band-platform

# Mint the Band agent using the installed package's registration script.
hermes_env="${HERMES_HOME:-$HOME/.hermes}/.env"
mkdir -p "$(dirname "$hermes_env")"
bash "$("$hermes_python" -c 'import hermes_band_platform; print(hermes_band_platform.__path__[0])')/scripts/register-agent.sh" | sed -n -e 's/^export //' -e '/^[A-Z_][A-Z0-9_]*=/p' >> "$hermes_env"
unset BAND_USER_API_KEY

# Enable the plugin, then hand off to the agent: the add-band skill restarts the gateway,
# wires Band in as a comms channel with context isolation, bootstraps the hub, and sends
# you the agent's first message — the steps that need agent smarts, not bash.
hermes plugins enable band
hermes chat -s add-band < /dev/tty
