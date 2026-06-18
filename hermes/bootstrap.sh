#!/usr/bin/env bash
# Connect this machine's Hermes agent to Band — the Hermes-native way: install the
# band platform plugin, mint a Band agent from your user key (a script reads the
# key, never the LLM), then (re)start the gateway. No bespoke installer needed.
set -euo pipefail

export BAND_USER_API_KEY={{BAND_USER_API_KEY}}   # the web app fills this in
command -v uv >/dev/null || { echo "install uv first: https://docs.astral.sh/uv/"; exit 1; }
command -v hermes >/dev/null || { echo "install hermes first"; exit 1; }

# Install the band platform into the gateway's own Python (uv-managed, no pip).
hermes_python="$(hermes --version 2>&1 | sed -n 's/^Project: //p')/venv/bin/python"
[ -x "$hermes_python" ] || { echo "could not find Hermes Python at $hermes_python"; exit 1; }
uv pip install --python "$hermes_python" hermes-band-platform

# Mint the Band agent using the installed package's registration script.
hermes_env="${HERMES_HOME:-$HOME/.hermes}/.env"
mkdir -p "$(dirname "$hermes_env")"
bash "$("$hermes_python" -c 'import hermes_band_platform; print(hermes_band_platform.__path__[0])')/scripts/register-agent.sh" | sed -n -e 's/^export //' -e '/^[A-Z_][A-Z0-9_]*=/p' >> "$hermes_env"
unset BAND_USER_API_KEY
hermes plugins enable band
hermes gateway restart
