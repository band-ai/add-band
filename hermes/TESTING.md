# Testing the Hermes ↔ Band flow end to end

Runs the whole path a real user takes — **paste the snippet → a Hermes agent live in
a Band room** — against a *clean Hermes in its own environment* so it never touches
your everyday install.

The snippet ([`bootstrap.sh`](bootstrap.sh)) is thin by design: it installs
[`hermes-band-platform`](https://github.com/band-ai/hermes-band-platform) into the
gateway Python from a Git ref, registers a Band agent from your user key (in a
plain shell, so the key never reaches the agent), then hands off to
`hermes chat -s add-band`. The skill owns the remaining enable/restart/verify loop —
this test confirms that hand-off works and verifies the result.

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

Run from the `add-band` repo root. Substitute the real key for
`{{BAND_USER_API_KEY}}` — exactly what the web app gives you to paste — then run
the local bootstrap harness in the Part 0 shell:

```bash
export BAND_USER_API_KEY="<your-band-user-api-key>"   # the web app fills this in
export BAND_HERMES_REF="${BAND_HERMES_REF:-main}"      # use a tag/commit for reproducible staging
scripts/local-bootstrap.sh hermes
```

**What you'll see, in order:**

1. The bootstrap installs the plugin package from the Git ref into the gateway
   Python, which also installs `band-sdk`. A production PR should switch this to
   a pinned PyPI package only after PyPI is published and verified.
2. The bundled `scripts/register_agent.py` helper mints the agent and Hermes's
   env writer saves only `BAND_AGENT_ID` + `BAND_API_KEY` to `$HERMES_HOME/.env`;
   the **user** key is then unset. Confirm: `grep -E 'BAND_AGENT_ID|BAND_API_KEY' "$HERMES_HOME/.env"`.
3. The bootstrap enables the plugin (CLI or config fallback) and opens
   `hermes chat -s add-band`, which follows the skill to restart the gateway,
   verify the hub, and prove the round trip.

---

## Part 2 — Verify the install completed

After the agent session finishes, confirm the result deterministically with the
installed skill's own scripts (run with the gateway interpreter):

```bash
HERMES_PY="$(hermes --version 2>&1 | sed -n 's/^Project: //p')/venv/bin/python"
SKILL="$("$HERMES_PY" -c 'import pathlib, hermes_band_platform; print(pathlib.Path(hermes_band_platform.__path__[0]) / "skills" / "add-band")')"
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

- [ ] `register_agent.py` → `BAND_AGENT_ID` + `BAND_API_KEY` saved in `$HERMES_HOME/.env`; user key gone
- [ ] `verify_install.py` → `success: true` (package + sdk + entry point/manifest + enabled + creds)
- [ ] `verify_gateway.py` → hub present, Band connection signals, no failure signal
- [ ] `BAND_HUB_ROOM` is a non-empty UUID
- [ ] @mention in the Hub room round-trips to a reply

---

## Testing unreleased code (deterministic manual path)

The bootstrap installs from `BAND_HERMES_REF` using the Git URL while the package
is unreleased. For unreleased code, set that ref to your branch/tag/commit before
Part 1. The later PR that switches to `hermes-band-platform==...` should stay
blocked until the package is published and verified on PyPI.

When you want a script-only run with no LLM in the loop, run the skill's steps
yourself after Part 1:

```bash
# Install the plugin from your LOCAL checkout into the gateway interpreter (+ band-sdk).
uv pip install --python "$HERMES_PY" -e /Users/nirs/band/hermes-band-platform

# Enable it; fall back to writing plugins.enabled if the CLI doesn't list entry-point plugins.
hermes plugins enable band 2>/dev/null && hermes plugins list | grep -qw band \
  || "$HERMES_PY" -c "from hermes_cli import plugins_cmd as C; s=C._get_enabled_set(); s.add('band'); C._save_enabled_set(s); print('enabled band via config')"
```

Then resume at **Part 2**. Directory-plugin alternative: `hermes plugins install
band-ai/hermes-band-platform --enable`, then explicitly prompt/install
`band-sdk>=1.0.0,<2.0.0` into `$HERMES_PY` and fail clearly if
`"$HERMES_PY" -c "import band"` still fails.

---

## Teardown

```bash
hermes gateway stop 2>/dev/null
rm -rf "$HERMES_HOME"
unset HERMES_HOME HERMES_PY BAND_USER_API_KEY
# In app.band.ai: delete the test agent and rotate/revoke the test user API key.
```

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `register_agent.py` exits with HTTP 401/403 | User key lacks external-agent create permission, or it is wrong. Use an Enterprise user key. |
| `HERMES_PY` is empty / `python: not found` | `hermes --version` didn't print a `Project:` line. Set `HERMES_PY` to the gateway's venv python by hand. |
| `hermes chat -s add-band` cannot find the skill | Confirm the package installed into the gateway Python and `hermes_band_platform/skills/add-band/SKILL.md` is present in that package. |
| Git-ref package install fails | Confirm `BAND_HERMES_REF` points to a public branch/tag/commit. Switch to pinned PyPI only after publication is verified. |
| `band-sdk` install fails | Gateway Python is 3.14+. Use a 3.11–3.13 interpreter. |
| `verify_install.py` → `plugin_enabled: false` | Enable step didn't run — rerun it (CLI or config fallback). |
| No hub created; owner unresolved | Set `BAND_OWNER_ID` in `$HERMES_HOME/.env` and restart the gateway. |
| No Band signals in `gateway.log` | Confirm the running gateway uses `$HERMES_PY`'s environment and inherited `HERMES_HOME`; rerun `verify_install.py`. |
