# Working agreements

`add-band` is the open catalog of Band on-ramps: one folder per agent harness
(`hermes/`, `openclaw/`, `nanoclaw/`, …) holding a thin `bootstrap.sh` +
`manifest.yaml` + guide, never the integration code itself — that lives
upstream and is pointed at, pinned. `pa-conformance/` is the live suite
proving the personal-agent harnesses actually come up headlessly and talk on
hosted Band. Start with the [README](README.md); details:
[CONTRIBUTING.md](CONTRIBUTING.md) (adding an integration),
[TESTING.md](TESTING.md) (local testing),
[pa-conformance/README.md](pa-conformance/README.md) (the live suite).

## Commands

```bash
python3 scripts/check.py          # validate the catalog (CI runs this)
pytest tests/ -q                  # catalog invariants
cd pa-conformance && E2E_TESTS_ENABLED=true uv run pytest tests -v --tb=short   # live suite (needs Band creds)
```

The pa-conformance workflow runs the same compose stacks + pytest command as a
local run with the same environment and selected harnesses. Credentials come
from `.env.test` at the repo root (copy
[.env.test.example](.env.test.example)) or exported env vars. Fresh machines
also need access to the pinned upstream repos and container/image downloads.
NanoClaw needs a one-time prepare against a dedicated disposable checkout/cache
path:

```bash
NANOCLAW_SRC=~/.cache/pa-nanoclaw/nanoclaw-band bash pa-conformance/stacks/nanoclaw/prepare.sh
```

The prepare script resets `NANOCLAW_SRC` to the requested upstream ref before
applying the Band payload; never point it at a user-edited NanoClaw working
tree. See the [suite README](pa-conformance/README.md).

## Rules

- **A new PA harness must add its conformance coverage** — a four-verb runner
  in `pa-conformance/harness/` plus a stack in `pa-conformance/stacks/`; the
  tests parametrize over the harness registry and are never hand-listed. See
  [CONTRIBUTING.md](CONTRIBUTING.md#personal-agents-conformance-is-part-of-the-integration).
- **Never vendor integration code here** — point at the upstream repo,
  pinned to a tag/commit.
- **Integration folders stay thin and complete** — a participating integration
  has `bootstrap.sh`, `manifest.yaml`, and a guide; stubs must be explicit in
  `scripts/check.py`.
- **Bootstrap snippets are user-safe** — they may prompt for secrets locally,
  but they must not bake secrets into files, logs, docs, examples, or agent
  instructions.
- **Absolute imports only** in Python (`from driver.sdk import …`, never
  `from .sdk import …`) — relative imports break the moment a module is
  imported from a different root.
- **No underscore-prefixed file or class names.** A leading `_` is for
  module-internal members only; files and classes are named by what they are
  (`probe_restart.py`, not `_probe_restart.py`). Keep a scratch file out of
  pytest collection by not matching `test_*.py`, not by prefixing.
- **Profile facts carry their evidence.** Every non-UNKNOWN field in a
  harness's `Profile` declaration (`pa-conformance/harness/*.py`) has an
  adjacent `#:` comment naming how it was validated — a live test/date or an
  upstream `file:line`. A fact without evidence is declared `UNKNOWN`, never
  guessed; review enforces the comment like any other fact.
- **Classify PA scenarios before adding an exception.** A core conformance
  test asserts behavior every participating PA must provide; it has no
  harness-specific exception. A declared capability uses
  `@pytest.mark.requires_profile(PROFILE_FIELD.<fact>)`: it runs only when the
  harness positively declares the evidenced fact, and `False` or `UNKNOWN`
  skips it with the profile-derived reason. Use `@pytest.mark.known_gap` only
  for an active, ticketed defect in a mandatory behavior: it still runs the
  target harness and turns a failure into an xfail, so it is never a way to
  encode an intentional policy difference, an unsupported capability, or LLM
  variance. `@pytest.mark.harness_skip` is for a scenario the suite cannot
  observe or drive for that harness; ordinary `skipif` is only a test
  prerequisite such as a required peer or local executable. Remove a
  `known_gap` when its ticket is fixed, canceled, or reclassified.
- **Comments and docs state facts, not history.** They capture what is true
  and non-obvious about the code as it stands — a constraint the code can't
  express, a platform behavior discovered live, a reason the simpler
  alternative doesn't work. Never change narration ("now uses", "instead of
  the old") — that story belongs in commit messages and PRs. If a comment
  only makes sense to someone who watched the change happen, rewrite it as
  the standing fact or delete it.
- **Review the catalog surface, not just code paths.** Check upstream pins,
  bootstrap safety, secret handling, docs accuracy, catalog invariants, and the
  validation commands above before treating an integration change as done.
