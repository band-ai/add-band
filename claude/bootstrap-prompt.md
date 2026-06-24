# Band.ai Tom & Jerry Bootstrap Instructions (Claude Code)

You are following the Band.ai Tom & Jerry onboarding instructions. The user has pasted text containing a Band.ai **user API key** and a link to this file. Your job is to:

1. Provision two new agents (Tom and Jerry) on the Band.ai platform using the user API key.
2. Scaffold a working standalone project locally that runs those agents, **by fetching the live example files from `band-ai/band-sdk-python` and transforming them** — no example code is bundled here.

## Source of truth

These instructions fetch two kinds of external resources, both always from `main`:

1. **`scripts/register-agent.sh`** from `band-ai/add-band` (the repo where this file lives) — the helper used to provision the agents in Step 5.
2. **Example agent files + `characters.py`** from `band-ai/band-sdk-python` — fetched and transformed in Step 6. `main` matches what `band-sdk` on PyPI is built from, so the scaffolded code and the installed library stay aligned.

These instructions may themselves be loaded from any branch (a feature branch during testing, `main` after merge) — no branch-sniffing is needed because everything they reference is pinned to `main`.

### Example file map (from `band-sdk-python/main`)

| Adapter | Tom file | Jerry file |
|---|---|---|
| `langgraph` | `examples/langgraph/07_tom_agent.py` | `examples/langgraph/08_jerry_agent.py` |
| `crewai` | `examples/crewai/05_tom_agent.py` | `examples/crewai/06_jerry_agent.py` |
| `anthropic` | `examples/anthropic/03_tom_agent.py` | `examples/anthropic/04_jerry_agent.py` |
| `claude_sdk` | `examples/claude_sdk/03_tom_agent.py` | `examples/claude_sdk/04_jerry_agent.py` |
| `parlant` | `examples/parlant/04_tom_agent.py` | `examples/parlant/05_jerry_agent.py` |
| `pydantic_ai` | `examples/pydantic_ai/03_tom_agent.py` | `examples/pydantic_ai/04_jerry_agent.py` |

The shared character prompts live at `examples/prompts/characters.py` — fetch verbatim, no transformation.

## Procedure

Follow these steps in order. Use AskUserQuestion for every user-facing prompt.

### Step 1 — Extract the user API key from the pasted text

Look in the conversation so far for:
- A **Band.ai user API key** (begins with `band_u_`).
- Optionally `BAND_REST_URL` and `BAND_WS_URL`. If absent, use the production defaults:
  - `BAND_REST_URL=https://app.band.ai`
  - `BAND_WS_URL=wss://app.band.ai/api/v1/socket/websocket`

If the user API key is missing, ask the user for it before proceeding.

**Tom and Jerry agent credentials are NOT in the pasted text** — they don't exist yet. They will be created in Step 5 by calling the Band.ai platform API with the user key.

### Step 2 — Ask which adapter (two-stage picker)

`AskUserQuestion` accepts at most 4 options, so we split the adapter pick into two questions. The second is only asked when the first selects the "framework" bucket.

**Step 2a — Ask the runtime category** (single-select, 4 options):

- **Framework + your LLM key** — Run inside an agent framework (langgraph / crewai / pydantic_ai). You provide an OpenAI or Anthropic API key.
- **Direct Anthropic SDK** — Plain Anthropic SDK loop. Needs an Anthropic API key. *(sets `adapter = anthropic`)*
- **Claude Agent SDK** — Uses the Claude Code subprocess. **No external LLM key needed** — requires Node.js 20+ and `npm install -g @anthropic-ai/claude-code`. *(sets `adapter = claude_sdk`)*
- **Parlant** — Conversation-modeling framework. Needs an OpenAI API key. *(sets `adapter = parlant`)*

**Step 2b — Ask the framework** *(only if Step 2a was "Framework + your LLM key")* (single-select, 3 options):

- **langgraph** — Graph-based, LangChain ecosystem.
- **crewai** — Role-based multi-agent.
- **pydantic_ai** — Pydantic AI agent.

### Step 3 — Ask which LLM (conditional)

| Adapter | LLM question | LLM env var |
|---|---|---|
| `anthropic` | Skip — Anthropic only | `ANTHROPIC_API_KEY` |
| `claude_sdk` | Skip — no external LLM | none |
| `parlant` | Skip — OpenAI only (default NLP service) | `OPENAI_API_KEY` |
| `crewai`, `langgraph`, `pydantic_ai` | Ask: OpenAI or Anthropic | matching key |

### Step 4 — Confirm output directory

Default to `./tom-jerry-agents/` in the cwd. Ask only if it already exists.

### Step 5 — Provision Tom and Jerry agents on Band.ai

Use the user API key from Step 1 to register two new agents on the platform. The canonical helper is shipped in this same repo at `scripts/register-agent.sh` — fetch and run it twice (once per agent) rather than reinventing the curl call.

The script reads `BAND_USER_API_KEY` from env (never argv — the key never lands in `ps`), `BAND_AGENT_NAME` and `BAND_AGENT_DESCRIPTION` to customize, and prints two lines to stdout that you capture:

```
BAND_AGENT_ID=<uuid>
BAND_API_KEY=<agent-key>
```

Run via Bash (foreground — these are short calls). Fetch the script once into a tempfile, export the env vars, then `eval` the script output for each agent so `BAND_AGENT_ID` and `BAND_API_KEY` land in the shell directly (same pattern other `add-band` integrations like `nanoclaw/bootstrap.sh` use):

```bash
REGISTER_URL="https://raw.githubusercontent.com/band-ai/add-band/main/scripts/register-agent.sh"
SCRIPT_FILE=$(mktemp) && curl -fsSL "$REGISTER_URL" -o "$SCRIPT_FILE"
export BAND_USER_API_KEY="<user-api-key-from-step-1>"

# Tom
export BAND_AGENT_NAME="Tom"
export BAND_AGENT_DESCRIPTION="A clever and persistent cat who loves to catch mice. Known for creative schemes and dramatic flair."
eval "$(bash "$SCRIPT_FILE")"
TOM_AGENT_ID="$BAND_AGENT_ID"
TOM_API_KEY="$BAND_API_KEY"

# Jerry
export BAND_AGENT_NAME="Jerry"
export BAND_AGENT_DESCRIPTION="A clever and friendly mouse who lives in a cozy hole. Smart, witty, and loves cheese."
eval "$(bash "$SCRIPT_FILE")"
JERRY_AGENT_ID="$BAND_AGENT_ID"
JERRY_API_KEY="$BAND_API_KEY"

# Clean up — user key + tempfile not needed past this point.
rm -f "$SCRIPT_FILE"
unset BAND_USER_API_KEY BAND_AGENT_NAME BAND_AGENT_DESCRIPTION BAND_AGENT_ID BAND_API_KEY
```

**Fail loudly on errors.** If either `curl … | bash` exits non-zero, or either `TOM_*` / `JERRY_*` variable comes back empty, STOP and surface the failure (including the script's stderr) to the user. Do NOT proceed to write any local files with half-provisioned agents — that leaves the user with an orphaned agent on the platform and a broken local setup. If only one of the two succeeded, tell the user explicitly so they know to clean it up on the platform before re-running.

**Special case — "name has already been taken":** if the script's stderr (or the response body it echoes) contains `has already been taken`, that's the platform telling you the user already has Band.ai agents named `Tom` and/or `Jerry` on their account — the platform enforces uniqueness on `(owner_id, name)`. STOP, clean up the tempfile and unset the env vars (same cleanup as the success path), then tell the user (use this wording or something close):

> ⚠️ **Can't continue — agents already exist.** You already have a Band.ai agent named **Tom** or **Jerry** on your account. These instructions need to create new ones with those exact names, and the platform won't allow duplicates. Please open the Band.ai UI and either **delete** the existing Tom/Jerry agents or **rename** them (e.g. `Tom-old`). Once that's done, reply here and I'll retry the provisioning step.

Then **wait for the user's reply** — do not retry on your own, do not move on to Step 6, do not write any files. When the user confirms they've cleaned up, retry Step 5 from the top. If they ask to abort, stop cleanly.

Keep `TOM_AGENT_ID`, `TOM_API_KEY`, `JERRY_AGENT_ID`, `JERRY_API_KEY` in memory for Step 7. Do NOT write the user API key anywhere on disk — it's used only here.

### Step 6 — Fetch and transform the example files

Fetch these three files from `band-ai/band-sdk-python` (always `main`):

1. `examples/prompts/characters.py`
2. The Tom file for the chosen adapter (see map above)
3. The Jerry file for the chosen adapter

**For `characters.py`**: write it verbatim to `<out>/characters.py`. No transformation.

**For each agent file**, apply the transformations below. They are pattern-based. If a pattern doesn't match (e.g. the example was already cleaned up), skip silently — that's fine. If something looks structurally different from what's documented here (e.g. a new shared import you don't recognize), STOP and tell the user before writing — don't guess.

#### Transformations to apply

1. **Strip PEP 723 inline script header.** Remove the entire block from `# /// script` to `# ///` inclusive (it's at the top of the file).

2. **Drop the sys.path hack.** Remove the line:
   ```python
   sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
   ```
   Also remove the `import sys` line if it's no longer used elsewhere in the file.

3. **Rewrite the characters import.** Change:
   ```python
   from prompts.characters import generate_tom_prompt   # or generate_jerry_prompt
   ```
   to:
   ```python
   from characters import generate_tom_prompt
   ```

4. **Replace the logging setup.** Change:
   ```python
   from setup_logging import setup_logging
   ...
   setup_logging()
   ```
   to:
   ```python
   import logging
   logging.basicConfig(level=logging.INFO)
   ```
   (Keep the existing `logger = logging.getLogger(__name__)` line.)

5. **Replace the module docstring.** The upstream example docstring describes how to run the file from the repo root and mentions `prompts/characters.py` — both are wrong for the scaffolded standalone project. Replace the entire top-of-file `"""..."""` block (the one immediately after `from __future__ import annotations`, if present, or otherwise the first triple-quoted string in the file) with a single-line docstring:

   - Tom file: `"""Tom the cat agent (<ADAPTER>)."""`
   - Jerry file: `"""Jerry the mouse agent (<ADAPTER>)."""`

   Where `<ADAPTER>` is the human-readable adapter name (LangGraph, CrewAI, Anthropic, Claude SDK, Parlant, Pydantic AI).

6. **Swap the LLM if the user picked something other than the example default.** The example defaults are listed below. Only modify if the user's choice differs.

   | Adapter | Example default | Anthropic swap | OpenAI swap |
   |---|---|---|---|
   | `langgraph` | `from langchain_openai import ChatOpenAI` + `ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"))` | replace import with `from langchain_anthropic import ChatAnthropic`, replace constructor with `ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"))` | already default |
   | `crewai` | `model="gpt-5.4-mini"` | `model="anthropic/claude-sonnet-4-5-20250929"` (litellm prefix) | already default |
   | `pydantic_ai` | `model="openai:gpt-5.4-mini"` | `model="anthropic:claude-sonnet-4-5-20250929"` | already default |
   | `anthropic`, `claude_sdk`, `parlant` | n/a — no swap path | — | — |

Write each transformed file to `<out>/tom_agent.py` and `<out>/jerry_agent.py`.

### Step 7 — Generate scaffolding files

Write these directly (they're scaffolding, not SDK code — no fetch needed). Substitute the bracketed values.

**`<out>/agent_config.yaml`** — uses the four values captured in Step 5:
```yaml
# Agent credentials from the Band.ai platform.
tom_agent:
  agent_id: "<TOM_AGENT_ID from Step 5>"
  api_key: "<TOM_API_KEY from Step 5>"

jerry_agent:
  agent_id: "<JERRY_AGENT_ID from Step 5>"
  api_key: "<JERRY_API_KEY from Step 5>"
```

**`<out>/.env`** — use the REST/WS URLs from Step 1, default to production if absent. The third line depends on the LLM choice:
- OpenAI → `OPENAI_API_KEY=`
- Anthropic (incl. the `anthropic` adapter) → `ANTHROPIC_API_KEY=`
- `claude_sdk` → omit entirely
- `parlant` → `OPENAI_API_KEY=`

```
BAND_REST_URL=<REST_URL>
BAND_WS_URL=<WS_URL>
<LLM_KEY_LINE>
```

**`<out>/pyproject.toml`** — `<EXTRA>` is the adapter name with two hyphen-form exceptions: `claude_sdk` → `claude-sdk`, `pydantic_ai` → `pydantic-ai`. The other adapters (`langgraph`, `crewai`, `anthropic`, `parlant`) use their name verbatim.

The `requires-python` upper bound matters: without it `uv` will pick the newest Python on the machine (3.14+ exists at time of writing), and pydantic-core's PyO3 currently caps at 3.13 — `uv sync` will fail to build. Cap at `<3.14`.

`<ANTHROPIC_DEPS>` is normally empty, but for crewai + Anthropic and pydantic_ai + Anthropic some extras don't get pulled in via the band-sdk extras and need to be added explicitly:

| Adapter + LLM | `<ANTHROPIC_DEPS>` content (a single line, indented to match) |
|---|---|
| `crewai` + Anthropic | `    "crewai[anthropic]==1.14.3",` |
| `pydantic_ai` + Anthropic | `    "pydantic-ai-slim[anthropic]>=1.56.0",` |
| Anything else | *(omit the line entirely)* |

```toml
[project]
name = "band-tom-jerry"
version = "0.1.0"
requires-python = ">=3.11,<3.14"
dependencies = [
    "band-sdk[<EXTRA>]>=1.1.0",
<ANTHROPIC_DEPS>
    "python-dotenv>=1.0.0",
]
```

**`<out>/.python-version`**
```
3.12
```

(Belt-and-suspenders with the `requires-python` cap — pins the interpreter explicitly so `uv sync` picks 3.12 instead of whatever the newest local Python happens to be.)

**`<out>/.gitignore`**
```
.env
agent_config.yaml
.venv/
__pycache__/
```

### Step 8 — Ask how to handle the LLM API key

Skip for `claude_sdk`.

AskUserQuestion (single-select, the question itself):
- **I'll add it to the .env myself** — show the path `<out>/.env` and which line to fill, then stop.
- **Add it for me now** — proceed to the next paragraph.

If the user picks **Add it for me now**, do NOT call `AskUserQuestion` again for the key itself — `AskUserQuestion` requires ≥2 options and the key is a free-form value. Instead, send a plain chat message like:

> Please paste your `<LLM_KEY_NAME>` here (e.g. `sk-ant-…` for Anthropic, `sk-…` for OpenAI) and I'll write it into `<out>/.env`.

Wait for the user's next message, then edit the `<LLM_KEY_NAME>=` line in `<out>/.env` to include the value.

### Step 9 — Ask who runs the agents

AskUserQuestion (single-select):
- **I'll run them myself** — show:
  ```
  cd <out>
  uv sync
  uv run python tom_agent.py     # terminal 1
  uv run python jerry_agent.py   # terminal 2
  ```
- **Claude, run them for me** — do these in order. Use the *exact* command form shown; small variations have broken past runs.

  1. **Foreground `uv sync`** in `<out>` and wait for it to finish. If it exits non-zero, STOP and surface the error — the background launches below assume `uv sync` succeeded.
     ```bash
     cd <out> && uv sync
     ```
  2. **Start Tom in its own Bash call** with `run_in_background: true`. Capture the returned bash ID as `TOM_BASH_ID`.
     ```bash
     cd <out> && uv run python tom_agent.py
     ```
  3. **Start Jerry in a SEPARATE Bash call** with `run_in_background: true`. Capture as `JERRY_BASH_ID`.
     ```bash
     cd <out> && uv run python jerry_agent.py
     ```
  4. Wait ~8 seconds, then `BashOutput` each ID and confirm you see `Agent started: Tom` and `Agent started: Jerry` log lines (and no Python traceback). If either failed, surface the error before moving on.
  5. Tell the user the two bash IDs and how to peek at logs (`BashOutput` with each ID).

  **Don't:**
  - Don't combine both agents into one Bash call — they're long-running processes; if you sequence them, Tom blocks forever and Jerry never starts.
  - Don't source `.venv/bin/activate` manually — `uv run python` handles the venv.
  - Don't substitute `python` or `python3` for `uv run python` — bare `python` picks up system Python without the project's deps.
  - Don't use `nohup` — Claude Code's `run_in_background: true` already detaches the process.
  - Don't try to use the Monitor tool here — these are long-lived processes, not bounded event streams.

### Step 10 — Show the user how to trigger the chase

Both agents are running and connected. To see them in action, present these steps to the user (copy the block below verbatim, just substitute the platform URL from `BAND_REST_URL` in their `.env`):

> **Watch Tom chase Jerry on the platform**
>
> 1. Open **<BAND_REST_URL>** in your browser and sign in.
> 2. In the left sidebar, click **Chats**.
> 3. Click **Start Your First Chat** — a new session opens.
> 4. In the **Participants** panel on the right, click the **+** next to the heading.
> 5. Select the **Tom** agent card, then click **Done**. Tom appears under **AGENTS** in the panel.
> 6. In the message box at the bottom, type `@Tom catch jerry` and hit send.
>
> Tom will look up Jerry, invite him into the chat automatically, and start trying to lure him out of his hole. The persuasion will escalate over up to 10 attempts — watch the back-and-forth in the chat, and tail the terminal logs (or the BashOutput stream if Claude is running them) if anything looks stuck.

Only add Tom as a participant — Tom finds and invites Jerry himself via the platform tools. Don't tell the user to add Jerry manually.

## Rules for Claude

- **Don't clone `band-ai/add-band` or `band-ai/band-sdk-python`.** Only fetch the specific files listed above.
- **The user API key is sensitive.** Pass it via env (never argv); use it only in Step 5; do not write it to any file on disk.
- **Don't bundle copies of the examples or `register-agent.sh`** in the generated project — they are fetched live, every time.
- **Don't walk the user through `characters.py`** — it's long and not relevant to onboarding.
- **If a transformation pattern fails to match**, that's usually fine (the example already changed in a compatible way). If the *structure* looks unfamiliar (new imports you don't recognize, the agent class name changed, the `Agent.from_config` shape is different), STOP and surface what's odd — don't fabricate a fix.
- **Respect existing files.** If `<out>/` is non-empty, ask before overwriting.
- **Stop after Step 10.** No refactors, no extra suggestions.
