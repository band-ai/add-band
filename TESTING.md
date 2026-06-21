# Testing a bootstrap locally

Every integration ships a hand-authored `bootstrap.sh`. Before a change to one ships,
test it the way a real user runs it. This guide is generic; an integration may also have
its own deeper end-to-end guide (for example [`hermes/TESTING.md`](hermes/TESTING.md)).

## How it reaches a user

The Band web app hands the user a `curl -fsSL <url> | bash` one-liner plus a Band **user
API key** to copy. The web app does **not** edit the script — the bootstrap **prompts**
for the key (reading from `/dev/tty`) and the user pastes it. Pre-set `BAND_USER_API_KEY`
to skip the prompt.

Two consequences worth testing for:

- **stdin is the pipe, not your terminal.** Under `curl … | bash`, stdin is the script
  itself. Anything interactive — the key prompt, an agent hand-off like
  `hermes chat -s add-band` — must read from `/dev/tty`, or it gets script text / EOF
  instead of the user.
- **no placeholder substitution.** A bootstrap that doesn't acquire `BAND_USER_API_KEY`
  itself (prompt, or accept a pre-set env var) never gets a key. `scripts/check.py`
  enforces that the snippet references `BAND_USER_API_KEY`.

## Static checks (no key, no side effects)

```bash
python3 scripts/check.py                  # validate the whole catalog (the CI gate)
python3 scripts/check.py --mini <harness> # preview the exact snippet the web app serves
pytest tests/ -q                          # drift + per-integration validation + bash -n
bash -n <harness>/bootstrap.sh            # syntax-only check of one script
```

## Run it locally (the real path)

`scripts/local-bootstrap.sh` runs a local `bootstrap.sh` exactly as `curl … | bash`
would — no key substitution; you'll be prompted (or pre-set `BAND_USER_API_KEY`):

```bash
scripts/local-bootstrap.sh <harness>          # default: cat … | bash (piped stdin, like curl|bash)
scripts/local-bootstrap.sh <harness> --curl   # curl -fsSL "file://…/bootstrap.sh" | bash
scripts/local-bootstrap.sh <harness> --print  # dry run: print the script, run nothing
```

Or by hand against your working copy:

```bash
# Prompt flow — you paste the key from /dev/tty, exactly like a real user:
curl -fsSL "file://$PWD/<harness>/bootstrap.sh" | bash

# Pre-set key (automation / no prompt). bash <(…) keeps your terminal on stdin:
BAND_USER_API_KEY="<your-band-user-api-key>" bash <(curl -fsSL "file://$PWD/<harness>/bootstrap.sh")
```

`curl … | bash` is the truer reproduction of what ships (piped stdin); `bash <(…)` is
handy when you'd rather not exercise the `/dev/tty` path.

## Isolate and clean up

Run against a throwaway home/config so your everyday install is untouched (Hermes, for
instance, honors `HERMES_HOME` — see [`hermes/TESTING.md`](hermes/TESTING.md)). Afterward,
delete the test agent at `app.band.ai` and rotate/revoke the test **user** API key. The
bootstraps `unset BAND_USER_API_KEY` once the agent is registered, so the broad key
doesn't linger in your shell.
