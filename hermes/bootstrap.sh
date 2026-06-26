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

# Band agent names must be unique per account, so a bare default collides on a
# second run (or with anyone else's "Hermes Agent") as "name has been taken".
# Offer a name with a unique default; pre-set BAND_AGENT_NAME to skip the prompt.
if [ -z "${BAND_AGENT_NAME:-}" ]; then
  default_name="Hermes Agent ($(hostname -s 2>/dev/null || echo local) $(date +%Y%m%d-%H%M%S))"
  if [ -r /dev/tty ]; then
    printf 'Agent name [%s]: ' "$default_name" >/dev/tty
    IFS= read -r BAND_AGENT_NAME </dev/tty
  fi
  BAND_AGENT_NAME="${BAND_AGENT_NAME:-$default_name}"
fi
export BAND_AGENT_NAME

# Mint the Band agent. The dependency-light `register-agent.sh` bundled with the
# add-band skill — the shared canonical helper, also used by the nanoclaw/openclaw
# bootstraps — does the registration and prints agent-scoped creds on stdout. The
# only Hermes-specific glue stays here: skipping a re-mint on re-run, and persisting
# the creds to the gateway .env through hermes_cli's env writer. Once band-sdk
# publishes `band.cli.register_agent`, swap the helper call for the SDK CLI — it must
# keep the helper's browser-like registration headers (User-Agent, Accept,
# Accept-Language) or app.band.ai can Cloudflare-1010 sparse script fingerprints
# even with a valid key.
skill_dir="$("$hermes_python" -c 'import pathlib, hermes_band_platform; print(pathlib.Path(hermes_band_platform.__path__[0]) / "skills" / "add-band")')"

# Idempotent: if the gateway already has an agent id persisted, don't mint another.
band_env="$(hermes config env-path 2>/dev/null || true)"
if [ -n "$band_env" ] && [ -f "$band_env" ] && grep -q '^BAND_AGENT_ID=' "$band_env"; then
  echo "Band agent already registered; skipping registration."
else
  # Keep registration non-interactive: BAND_AGENT_NAME is already set above; pin a
  # description default too so the helper doesn't drop into its /dev/tty prompt.
  : "${BAND_AGENT_DESCRIPTION:=Hermes agent on Band}"
  export BAND_AGENT_DESCRIPTION
  # The helper reads BAND_API_KEY from the env (never argv) and prints only the
  # agent-scoped BAND_AGENT_ID + BAND_AGENT_API_KEY — never the user key.
  creds="$(bash "$skill_dir/scripts/register-agent.sh")" \
    || { echo "Band registration failed (see the error above)." >&2; exit 1; }
  eval "$creds"
  [ -n "${BAND_AGENT_ID:-}" ] && [ -n "${BAND_AGENT_API_KEY:-}" ] \
    || { echo "registration returned no agent credentials" >&2; exit 1; }
  # Persist agent-scoped creds via Hermes's env writer (managed-scope/denylist/ASCII
  # guards live there). The agent key is stored under BAND_API_KEY — the name the
  # band plugin reads at runtime — and passed via the env, never argv.
  BAND_AGENT_ID="$BAND_AGENT_ID" BAND_AGENT_API_KEY="$BAND_AGENT_API_KEY" "$hermes_python" <<'PY'
import os
from hermes_cli.config import save_env_value
save_env_value("BAND_AGENT_ID", os.environ["BAND_AGENT_ID"])
save_env_value("BAND_API_KEY", os.environ["BAND_AGENT_API_KEY"])
PY
fi
# The user key (and the agent key we just persisted) must not linger into handoff.
unset BAND_API_KEY BAND_AGENT_API_KEY

# `hermes plugins enable` only sees directory plugins, not entry-point packages
# like band, so it prints a benign "not installed or bundled" on stdout and fails;
# silence both streams and let the config-write fallback enable it. (When the CLI
# learns to enable entry-point plugins, this public path will just start working.)
hermes plugins enable band >/dev/null 2>&1 && hermes plugins list | grep -qw band \
  || "$hermes_python" -c "from hermes_cli import plugins_cmd as C; s=C._get_enabled_set(); s.add('band'); C._save_enabled_set(s); print('enabled band via config')"
# The band plugin namespaces its skills, so the skill resolves as `band:add-band`,
# not the bare `add-band` (plugin skills never enter the flat ~/.hermes/skills tree).
hermes chat -s band:add-band < /dev/tty
