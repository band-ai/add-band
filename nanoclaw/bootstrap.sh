#!/usr/bin/env bash
# Connect this machine's NanoClaw agent to Band. Run from your NanoClaw checkout
# (or from an empty dir to set one up fresh from the Band-ready fork).
#
# What this does that the add-band *skill* doesn't: put you on a seam-equipped Band
# base (merge band-ai/main into an existing checkout, or clone the fork fresh), mint
# a Band agent from your user key, and stash its agent key in the OneCLI vault. Then
# it hands off to the skill, which copies the Band files in from band-ai/band/adapter
# (additively — no git merge, no tags), adds the self-registration imports, installs
# the pinned SDK, builds, and wires the room.
#
# Credentials land in two places, because Band has two consumers:
#   - the OneCLI vault (host-pattern app.band.ai, X-API-Key) for the container
#     band_* tools — OneCLI injects on egress, so no raw key enters a container.
#   - .env (BAND_AGENT_ID + BAND_AGENT_API_KEY) for the host ingestion adapter
#     (src/modules/band-config.ts), which reads the raw key directly — it isn't
#     behind the OneCLI egress proxy.
set -euo pipefail

FORK_REMOTE=band-ai
FORK_URL="${NANOCLAW_REPO:-https://github.com/band-ai/nanoclaw-band}"
SKILL_DIR=.claude/skills/add-band

command -v git >/dev/null 2>&1 || { echo "install git first" >&2; exit 1; }
is_nanoclaw() { [ -e "$1/.git" ] && { [ -f "$1/nanoclaw.sh" ] || [ -f "$1/container/agent-runner/package.json" ] || grep -q '"name": *"nanoclaw"' "$1/package.json" 2>/dev/null; }; }

# 0. Decide where the Band-ready NanoClaw checkout lives — never clone behind your
#    back into a hidden $HOME dir, and never clobber a non-NanoClaw directory.
#      NANOCLAW_HOME set       → honor it (explicit override)
#      pwd is a NanoClaw clone → use it in place (we bring it to the seam base)
#      pwd is empty            → clone the fork right here
#      pwd is anything else    → clone into ./nanoclaw-band
if [ -z "${NANOCLAW_HOME:-}" ]; then
  if is_nanoclaw "$PWD"; then NANOCLAW_HOME="$PWD"
  elif [ -z "$(ls -A . 2>/dev/null)" ]; then NANOCLAW_HOME="$PWD"
  else NANOCLAW_HOME="$PWD/nanoclaw-band"; fi
fi

# 1. Make NANOCLAW_HOME a seam-equipped Band checkout.
if is_nanoclaw "$NANOCLAW_HOME"; then
  # Existing checkout: bring it up to the fork's seam base. Merge band-ai/main to
  # land the core *seams* + the skill (seams edit core files, so they can't be
  # copied in additively). No-op if you're already current — and a no-op merge
  # succeeds even with a dirty tree (other channels mid-setup). If it CAN'T merge —
  # uncommitted changes while behind, or real divergence — do NOT force it and do
  # NOT drop files into the worktree: stray files would block the very
  # `git merge band-ai/main` that fixes the base (the conflict debacle). Bail with
  # guidance, leaving the tree exactly as we found it.
  cd "$NANOCLAW_HOME"
  git remote get-url "$FORK_REMOTE" >/dev/null 2>&1 || git remote add "$FORK_REMOTE" "$FORK_URL"
  git fetch -q "$FORK_REMOTE"
  if ! git merge --no-edit "$FORK_REMOTE/main" >/dev/null 2>&1; then
    git merge --abort >/dev/null 2>&1 || true
    [ -f "$SKILL_DIR/SKILL.md" ] || {
      echo "Can't merge $FORK_REMOTE/main into this checkout (uncommitted changes while behind, or divergence)," >&2
      echo "and the Band seam base isn't here yet. On a CLEAN tree run:  git merge $FORK_REMOTE/main  (stash first if needed)," >&2
      echo "then re-run this. (Bailing rather than dropping skill files that would block that merge.)" >&2
      exit 1
    }
    # else: the base already carries the skill (perhaps a little behind) — proceed;
    # the skill's seam pre-flight catches a base too old for the current payload.
  fi
elif [ -e "$NANOCLAW_HOME" ] && [ -n "$(ls -A "$NANOCLAW_HOME" 2>/dev/null)" ]; then
  echo "band: $NANOCLAW_HOME exists but isn't a NanoClaw checkout." >&2
  echo "      Re-run from an empty directory, or set NANOCLAW_HOME to where the fork should live." >&2
  exit 1
else
  # No checkout here — clone the Band-ready fork fresh (main already carries the
  # seams + skill). The skill fetches band/adapter (the payload) from this remote.
  git clone --depth 1 --branch main "$FORK_URL" "$NANOCLAW_HOME"
  cd "$NANOCLAW_HOME"
  git remote get-url "$FORK_REMOTE" >/dev/null 2>&1 || git remote add "$FORK_REMOTE" "$FORK_URL"
fi

# 2. The agent key lives in the OneCLI vault (the container reads it there, not from
#    .env), so registration below needs OneCLI. If it's missing the checkout is still
#    Band-ready — set up OneCLI, then re-run.
command -v onecli >/dev/null 2>&1 || {
  echo "Checkout is Band-ready at $NANOCLAW_HOME, but OneCLI isn't installed (NanoClaw routes agent creds through its vault)." >&2
  echo "cd $NANOCLAW_HOME, run /init-onecli, then re-run this to register your Band agent." >&2
  exit 1
}

# 3. Already wired? A Band secret in the vault + an agent id in .env => skip
#    registration. Source of truth is OneCLI, not .env, so re-pasting never mints a
#    duplicate agent.
band_ready() {
  onecli secrets list 2>/dev/null | grep -qi 'band' && grep -q '^BAND_AGENT_ID=' .env 2>/dev/null
}

if ! band_ready; then
  # 4. Create-scope key: use the web-app placeholder if it was substituted; else
  #    leave unset so register-agent.sh prompts on /dev/tty (works under
  #    `curl | bash`). The {{BAND_USER_API_KEY}} token stays for the web app and the
  #    catalog's check.py; this tolerates it being unsubstituted.
  USER_KEY='{{BAND_USER_API_KEY}}'
  case "$USER_KEY" in *'{{'*) : ;; *) export BAND_API_KEY="$USER_KEY" ;; esac

  # 5. Mint the Band agent via the skill's hardened helper (key never on argv, HTTP
  #    status checked, jq/python3 — no node; no eval). It prints dotenv on stdout.
  #    We don't default BAND_AGENT_NAME — the helper prompts for a unique name, and a
  #    fixed default collides on the second install (HTTP 422 "name already taken").
  umask 077
  creds=$(mktemp)
  trap 'rm -f "${creds:-}" 2>/dev/null' EXIT
  "$SKILL_DIR/scripts/register-agent.sh" > "$creds"
  AGENT_ID=$(grep '^BAND_AGENT_ID=' "$creds" | cut -d= -f2- || true)
  AGENT_KEY=$(grep -E '^BAND(_AGENT)?_API_KEY=' "$creds" | head -1 | cut -d= -f2- || true)
  rm -f "$creds"; trap - EXIT
  [ -n "$AGENT_ID" ] && [ -n "$AGENT_KEY" ] || { echo "registration returned no agent id/key" >&2; exit 1; }

  # 6. Stash the agent key in the OneCLI vault — the container band_* tools get it
  #    injected on egress (Band authenticates with X-API-Key; Bearer returns 401).
  #    (--value puts the key on argv; every add-* skill does the same — it's the
  #    documented `onecli secrets create` interface.)
  onecli secrets create --name Band --type generic --value "$AGENT_KEY" \
    --host-pattern app.band.ai --header-name X-API-Key --value-format '{value}'

  # 7. Persist identity + key to .env. The host ingestion adapter
  #    (src/modules/band-config.ts) reads the raw BAND_AGENT_API_KEY directly
  #    (canonical; BAND_API_KEY is the legacy fallback) — it isn't behind the OneCLI
  #    egress proxy — so the key lives here too, alongside the vault secret.
  grep -q  '^BAND_AGENT_ID=' .env 2>/dev/null         || echo "BAND_AGENT_ID=$AGENT_ID" >> .env
  grep -qE '^BAND(_AGENT)?_API_KEY=' .env 2>/dev/null || echo "BAND_AGENT_API_KEY=$AGENT_KEY" >> .env
  unset AGENT_KEY BAND_API_KEY

  echo "Registered Band agent $AGENT_ID; key written to .env (host adapter) and the OneCLI vault (containers)."
  echo "If the agent group's OneCLI secretMode is 'selective', grant it this secret (see /manage-channels)."
fi

# 8. Hand off to the add-band skill — it owns the real install (copy from
#    band-ai/band/adapter, imports, pinned deps, build, verify) and room wiring.
#    `< /dev/tty` gives the skill the real terminal even under `curl | bash`.
if command -v claude >/dev/null 2>&1; then claude /add-band < /dev/tty
else cat "$SKILL_DIR/SKILL.md"; fi
