# Testing the Hermes ↔ Band flow end to end

Runs the whole path a real user takes — **paste the snippet → a Hermes agent live in
a Band room** — against a *clean Hermes in its own environment* so it never touches
your everyday install.

The snippet ([`bootstrap.sh`](bootstrap.sh)) is thin by design: it installs
[`hermes-band-platform`](https://github.com/band-ai/hermes-band-platform) from a
Git ref as a Hermes **directory plugin** — the repo's `install.sh` stages
`$HERMES_HOME/plugins/band` and resolves `band-sdk` into `$HERMES_HOME/band-libs`,
writing nothing to the gateway venv — registers a Band agent from your Band API
key (in a plain shell, so the key never reaches the agent), then hands off to
`hermes chat -s band:add-band`. The skill owns the remaining restart/verify loop —
this test confirms that hand-off works and verifies the result.

## Prereqs

- A **Band account** and an **API key that can create external agents** (Enterprise).
- `git` and `uv` on PATH (the bootstrap checks both; `install.sh` resolves the SDK
  with `uv pip install --target`), plus network access to clone
  `band-ai/hermes-band-platform`.
- The gateway must run on **Python 3.11–3.13** (`band-sdk` has no 3.14 wheels yet).

The bootstrap registers the agent before the Hermes session starts. Verification
still requires an **@mention** in Band.

---

## Part 0 — A clean Hermes in its own env

```bash
# 0a. Install Hermes if `hermes` isn't already on PATH (skip otherwise).
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.zshrc   # or ~/.bashrc

# 0b. Isolate EVERYTHING this test does in a throwaway Hermes home. Config,
#     credentials (.env), logs, planted skills, and plugin enablement all live
#     here — your real ~/.hermes is untouched. Keep this ONE shell open for the
#     whole test; every `hermes` call below (and the pasted snippet) inherits it.
export HERMES_HOME="$HOME/.hermes-band-test"
mkdir -p "$HERMES_HOME"

# 0c. Make it a *working agent* — the skill runs as a Hermes agent (model + auth + terminal tool).
hermes setup            # full wizard (model, auth, tools)…
# hermes model          # …or just the model step — pick OpenAI as the provider, choose a model.
# hermes setup --portal # …or one Nous Portal OAuth login that covers the model.

# 0c-alt. (Optional) Give the agent a baseline comms channel — e.g. Telegram — *before* Band,
#         to prove the gateway works end to end on a channel you control. Create a bot with
#         @BotFather, then add only Telegram creds to THIS home's .env (the gateway activates
#         any platform whose creds are present, so leaving the others unset keeps it Telegram-only):
#   printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_ALLOWED_USERS=%s\n' "<token>" "<your-user-id>" >> "$HERMES_HOME/.env"
#   hermes gateway setup && hermes gateway start   # then message the bot to confirm it replies.

# 0d. Confirm the gateway interpreter is 3.11–3.13, then that the agent actually talks.
hermes --version
hermes                  # say "hi", get a reply, exit. No reply ⇒ fix model/auth before continuing.
```

> **Want zero shared state (not even the Python venv)?** Run the whole test in the
> container Hermes ships (`hermes-band/Dockerfile` + `docker-compose.yml`). `HERMES_HOME`
> isolates runtime state but shares the installed binary/venv — fine for testing,
> since the Band plugin is only *enabled* inside this home.

---

## Part 1 — The copy-paste (the actual user flow)

Run from the `add-band` repo root with the Part 0 shell still active. Set your
Band API key, then run the local bootstrap harness:

```bash
export BAND_API_KEY="<your-band-api-key>"
export BAND_HERMES_REF="${BAND_HERMES_REF:-main}"  # use a tag/commit for reproducible testing
scripts/local-bootstrap.sh hermes
```

> **Testing live plugin edits?** Copy `hermes/bootstrap.sh` to a **git-ignored**
> `hermes/bootstrap.local.sh` and replace its clone + `install.sh` block with your
> local checkout's own installer
> (`bash "$HOME/path/to/hermes-band-platform/install.sh"`). A directory plugin is a
> *copy*, so re-run it after every edit — there is no editable install.
> `scripts/local-bootstrap.sh hermes` prefers the override automatically, or curl it
> directly — run from the repo root, with `HERMES_HOME` exported in this shell:
>
> ```bash
> curl -fsSL "file://$PWD/hermes/bootstrap.local.sh" | bash
> ```

**What you'll see, in order:**

1. The bootstrap clones the Git ref and runs its `install.sh`: the plugin is staged
   into `$HERMES_HOME/plugins/band`, `band-sdk` is resolved into
   `$HERMES_HOME/band-libs` with the gateway interpreter, and `band` is enabled.
   Watch for its `gateway python:`, `band-sdk OK:`, and `plugin dir:` lines.
2. The bundled `scripts/register-agent.sh` helper mints the agent and prints the
   agent-scoped pair; the bootstrap saves only `BAND_AGENT_ID` + `BAND_API_KEY`
   (the agent-scoped key, replacing your broad key of the same name) to
   `$HERMES_HOME/.env` through Hermes's env writer; the broad shell value is then
   unset. The helper sends browser-like registration headers
   because sparse script fingerprints can trip Cloudflare 1010 at `app.band.ai`;
   preserve that behavior when replacing it with the SDK CLI.
   Confirm: `grep -E 'BAND_AGENT_ID|BAND_API_KEY' "$HERMES_HOME/.env"`.
3. The bootstrap opens `hermes chat -s band:add-band` (the plugin namespaces its
   skills), which follows the skill to restart the gateway, verify the hub, and
   prove the round trip.

---

## Part 2 — Verify the install completed

After the agent session finishes, confirm the result deterministically with the
installed skill's own scripts (run with the gateway interpreter):

```bash
# The installed plugin dir is the skill's home, and its own resolver finds the
# gateway interpreter the same way install.sh does (HERMES_PY overrides).
SKILL="${HERMES_HOME:-$HOME/.hermes}/plugins/band/skills/add-band"
HERMES_PY="$(python3 "$SKILL/scripts/gateway_python.py" --print)"
"$HERMES_PY" "$SKILL/scripts/verify_install.py"   # expect "success": true, empty "blocking"

# If the gateway isn't already running from the agent's restart, start it from THIS
# shell so it inherits HERMES_HOME (first connect creates the hub + writes BAND_HUB_ROOM):
hermes gateway setup   # first time only
hermes gateway start

"$HERMES_PY" "$SKILL/scripts/verify_gateway.py"   # expect hub + Band connection signals

# Raw signals, if you want to look directly:
grep -E '\[band\] Connected as agent|\[band\] Hub ready: room|✓ band connected' "$HERMES_HOME/logs/gateway.log"
grep BAND_HUB_ROOM "$HERMES_HOME/.env"   # a non-empty UUID ⇒ hub created
```

---

## Part 3 — The live Band loop

1. Open Band, find the auto-created **"Hermes Agent Hub"** room.
2. **@mention** the agent. A reply means you're live.
3. Band has no DMs — an un-mentioned message is ignored by design, so always @mention.

---

## Pass/fail checklist

- [ ] `register-agent.sh` → `BAND_AGENT_ID` + `BAND_API_KEY` (agent-scoped) saved in `$HERMES_HOME/.env`; broad Band key gone from the shell
- [ ] `verify_install.py` → `success: true` with an empty `blocking` (sdk + band-libs on `sys.path` + directory manifest + enabled + creds + access policy). A correct directory install still lists `package_importable`/`entry_point` under `missing` — that layout has neither, by design — so read `blocking`, not `missing`
- [ ] `verify_gateway.py` → hub present, Band connection signals, no failure signal
- [ ] `BAND_HUB_ROOM` is a non-empty UUID
- [ ] @mention in the Hub room round-trips to a reply

---

## Testing unreleased code (deterministic manual path)

The bootstrap installs `BAND_HERMES_REF` from Git. Set it to the branch, tag, or
commit under test before Part 1.

When you want a script-only run with no LLM in the loop, install from your local
checkout after Part 1. `install.sh` stages the plugin, resolves the SDK, and
enables `band`, so it replaces the whole install/enable dance:

```bash
bash /path/to/hermes-band-platform/install.sh
```

Then resume at **Part 2**. Package alternative, only on a *writable* gateway venv
— `install.sh` refuses to run while a pip copy shadows the directory plugin, since
an entry-point install overrides it and would keep the old code running:

```bash
uv pip install --python "$HERMES_PY" \
  "hermes-band @ git+https://github.com/band-ai/hermes-band-platform.git@${BAND_HERMES_REF:-main}"
hermes plugins enable band
```

---

## Teardown

```bash
hermes gateway stop 2>/dev/null
rm -rf "$HERMES_HOME"
unset HERMES_HOME HERMES_PY BAND_API_KEY
# In app.band.ai: delete the test agent and rotate/revoke the test API key.
```

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `register-agent.sh` exits with HTTP 401/403 | Band API key lacks external-agent create permission, or it is wrong. Use an Enterprise key. |
| `HERMES_PY` is empty / `python: not found` | `gateway_python.py --print` could not resolve the gateway interpreter. Diagnose with `python3 "$SKILL/scripts/gateway_python.py"`, or set `HERMES_PY` by hand — it needs Python 3.11–3.13 with `hermes_cli` importable. |
| `hermes chat -s band:add-band` cannot find the skill | Confirm `$HERMES_HOME/plugins/band/skills/add-band/SKILL.md` exists and `hermes plugins list` shows `band`. Plugin skills are namespaced, so the bare `add-band` will not resolve. |
| `install.sh` refuses: a pip copy shadows the directory plugin | An entry-point install of `hermes-band` (or the pre-rename `hermes-band-platform`) overrides it. Remove it with `uv pip uninstall --python "$HERMES_PY" <name>`, or re-run with `BAND_UNINSTALL_PIP=1`. |
| Git clone of the ref fails | Confirm `BAND_HERMES_REF` points to a public branch, tag, or commit. |
| `band-sdk` resolve fails | Gateway Python is 3.14+. Use a 3.11–3.13 interpreter. |
| `verify_install.py` → `plugin_enabled: false` | `hermes plugins enable band`, then confirm with `hermes plugins list`. `install.sh` does this itself and fails loudly if it can't, so a false here means the installer never reached step 5. |
| No hub created; owner unresolved | Set `BAND_OWNER_ID` in `$HERMES_HOME/.env` and restart the gateway. |
| No Band signals in `gateway.log` | Confirm the running gateway uses `$HERMES_PY`'s environment and inherited `HERMES_HOME`; rerun `verify_install.py`. |
