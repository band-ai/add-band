# Testing the Hermes ↔ Band flow end to end

Runs the whole path a real user takes — **paste the snippet → a Hermes agent live in
a Band room** — against a *clean Hermes in its own environment* so it never touches
your everyday install.

The snippet ([`bootstrap.sh`](bootstrap.sh)) is thin by design: it clones
[`hermes-band-platform`](https://github.com/band-ai/hermes-band-platform), registers
a Band agent from your user key (in a plain shell, so the key never reaches the
agent), plants the `add-band` **skill**, then hands off to `hermes /add-band`. The
skill owns install/enable/restart/verify — this test confirms that hand-off works and
verifies the result.

## Prereqs

- A **Band account** and a **user API key that can create external agents** (Enterprise).
  This is the only thing you supply by hand — the web app fills it in for real users.
- `git`, and network access to clone `band-ai/hermes-band-platform`.
- The gateway must run on **Python 3.11–3.13** (`band-sdk` has no 3.14 wheels yet).

The only human gate left is the **@mention** in Band — the snippet now handles the
credential step before the agent ever runs.

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
# hermes setup --portal # …or one Nous Portal OAuth login that covers the model.

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

Substitute the real key for `{{BAND_USER_API_KEY}}` — exactly what the web app does —
then paste the snippet in the Part 0 shell:

```bash
export BAND_USER_API_KEY="<your-band-user-api-key>"   # the web app fills this in
rm -rf /tmp/hbp && git clone --depth 1 --branch main https://github.com/band-ai/hermes-band-platform /tmp/hbp
SKILL=/tmp/hbp/hermes_band_platform/skills/add-band
HERMES_PY="$(hermes --version 2>&1 | sed -n 's/^Project: //p')/venv/bin/python"
"$HERMES_PY" "$SKILL/scripts/register_agent.py"
unset BAND_USER_API_KEY
DEST="${HERMES_HOME:-$HOME/.hermes}/skills/add-band"
rm -rf "$DEST" && mkdir -p "$(dirname "$DEST")" && cp -r "$SKILL" "$DEST"
hermes /add-band
```

**What you'll see, in order:**

1. `register_agent.py` prints `{"success": true, "agent_id": "…", "saved": ["BAND_AGENT_ID", "BAND_API_KEY"]}`
   — your **user** key was used once and dropped; only agent-scoped creds were written
   to `$HERMES_HOME/.env`. Confirm: `grep -E 'BAND_AGENT_ID|BAND_API_KEY' "$HERMES_HOME/.env"`.
2. The skill is copied to `$HERMES_HOME/skills/add-band` — that's what makes
   `hermes /add-band` invocable on this fresh home.
3. `hermes /add-band` opens an agent session that **follows the skill**: install the
   plugin, enable it, restart the gateway, verify the hub. Answer any prompts; because
   credentials are already saved, it goes straight past the credential step.

---

## Part 2 — Verify the install completed

After the agent session finishes, confirm the result deterministically with the
skill's own scripts (run with the gateway interpreter):

```bash
"$HERMES_PY" "$SKILL/scripts/verify_install.py"   # expect "success": true, empty "missing"

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

- [ ] `register_agent.py` → `success: true`; `BAND_AGENT_ID` + `BAND_API_KEY` in `$HERMES_HOME/.env`; user key gone
- [ ] `verify_install.py` → `success: true` (package + sdk + entry point/manifest + enabled + creds)
- [ ] `verify_gateway.py` → hub present, Band connection signals, no failure signal
- [ ] `BAND_HUB_ROOM` is a non-empty UUID
- [ ] @mention in the Hub room round-trips to a reply

---

## Testing unreleased code (deterministic manual path)

The hand-off agent runs `uv pip install hermes-band-platform` — which **fails until
the package is published to PyPI**. While it's unreleased (or when you want a
script-only run with no LLM in the loop), do Part 1 through the `register_agent.py` +
plant lines, then **skip `hermes /add-band`** and run the skill's steps yourself:

```bash
# Install the plugin from your LOCAL checkout into the gateway interpreter (+ band-sdk).
uv pip install --python "$HERMES_PY" -e /Users/nirs/band/hermes-band-platform

# Enable it; fall back to writing plugins.enabled if the CLI doesn't list entry-point plugins.
hermes plugins enable band 2>/dev/null && hermes plugins list | grep -qw band \
  || "$HERMES_PY" -c "from hermes_cli import plugins_cmd as C; s=C._get_enabled_set(); s.add('band'); C._save_enabled_set(s); print('enabled band via config')"
```

Then resume at **Part 2**. (Directory-plugin alternative: `hermes plugins install
band-ai/hermes-band-platform --enable` then `uv pip install --python "$HERMES_PY"
'band-sdk>=1.0.0,<2.0.0'`.)

---

## Teardown

```bash
hermes gateway stop 2>/dev/null
rm -rf "$HERMES_HOME" /tmp/hbp
unset HERMES_HOME HERMES_PY BAND_USER_API_KEY
# In app.band.ai: delete the test agent and rotate/revoke the test user API key.
```

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `register_agent.py` → `success: false`, HTTP 401/403 | User key lacks external-agent create permission, or it's wrong. Use an Enterprise user key. |
| `HERMES_PY` is empty / `python: not found` | `hermes --version` didn't print a `Project:` line. Set `HERMES_PY` to the gateway's venv python by hand. |
| `hermes /add-band` → "unknown command" | Skill wasn't planted into the home the running `hermes` uses. Confirm `$HERMES_HOME/skills/add-band/SKILL.md` exists and `HERMES_HOME` is exported in this shell. |
| Agent's `pip install` fails | Package not on PyPI yet — use the manual path above. |
| `band-sdk` install fails | Gateway Python is 3.14+. Use a 3.11–3.13 interpreter. |
| `verify_install.py` → `plugin_enabled: false` | Enable step didn't run — rerun it (CLI or config fallback). |
| No hub created; owner unresolved | Set `BAND_OWNER_ID` in `$HERMES_HOME/.env` and restart the gateway. |
| No Band signals in `gateway.log` | Confirm the running gateway uses `$HERMES_PY`'s environment and inherited `HERMES_HOME`; rerun `verify_install.py`. |
