"""Hermes runner.

Bring-up follows hermes-band-platform's add-band SKILL.md, headless form. The
Band plugin is baked into a derived image (stacks/hermes/Dockerfile);
everything else is bind-mounted state under $HERMES_HOME, which the runner
pre-writes before first start:

  - `.env` — the injected identity (the plugin stores the agent key as
    BAND_API_KEY) plus BAND_BASE_URL.
  - `config.yaml` — `plugins.enabled: [band]` (plugins are opt-in; the config
    key is the documented fallback for enabling entry-point plugins) and the
    model pin (Hermes has no default model — an empty `model` means the
    gateway has nothing to answer with; provider `anthropic` binds it to the
    ANTHROPIC_API_KEY passed through the compose environment).

The plugin's ensure_access_policy.py is required: without the allowlist policy,
the gateway rejects every sender, including the owner. A restart then picks up
the written policy.

Readiness is the plugin's own verify_gateway.py reporting success (hub room
created + owner resolved — a real Band round-trip, not a process-up check).
"""

from __future__ import annotations

import json
import os

from pa_settings import pa_settings

from harness.compose import ComposeStack
from harness.contract import STACKS_DIR, BandIdentity, Harness, wait_for

_VENV_PY = "/opt/hermes/.venv/bin/python"

#: Locates the plugin's bundled add-band scripts inside the container.
_SCRIPTS_DIR = (
    f'$({_VENV_PY} -c "import hermes_band_platform as p, pathlib; '
    "print(pathlib.Path(p.__file__).parent / 'skills/add-band/scripts')\")"
)


class HermesHarness(Harness):
    name = "hermes"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.home = self.workdir / "home"
        self.stack = ComposeStack(
            file=STACKS_DIR / "hermes" / "compose.yaml",
            project=f"pa-hermes-{ctx.run_id}",
            env={
                "PA_HERMES_HOME": str(self.home),
                "PA_UID": str(os.getuid()),
                "PA_GID": str(os.getgid()),
                # The plugin commit baked into the image (pin from pins.env).
                "BAND_HERMES_REF": pa_settings().band_hermes_ref,
                **ctx.llm_env,
            },
        )
        # Provider keys ride the compose env; scrub them from any surfaced
        # output alongside the agent key registered in up().
        self.stack.redactions |= set(ctx.llm_env.values())

    def up(self, identity: BandIdentity) -> None:
        self.stack.redactions.add(identity.api_key)  # scrub it from logs()
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / ".env").write_text(
            f"BAND_AGENT_ID={identity.agent_id}\n"
            f"BAND_API_KEY={identity.api_key}\n"
            f"BAND_BASE_URL={self.ctx.band_base_url}\n"
        )
        # Two settings keep a Band room the only conversational scope (both
        # default the wrong way for room isolation):
        #   - memory.memory_enabled: Hermes's curated MEMORY.md persists across
        #     sessions and is agent-global — left on it re-injects one room's
        #     remembered facts into every other room's system prompt.
        #   - group_sessions_per_user: the gateway default (true) keys the
        #     session/conversation history per user, so the same user's turns in
        #     room A surface when the agent searches "this room's" history in
        #     room B. Band rooms are one shared channel → false (room = session).
        # The per-room session transcript remains the in-room memory.
        (self.home / "config.yaml").write_text(
            f"model:\n"
            f"  default: {self.ctx.anthropic_model}\n"
            f"  provider: anthropic\n"
            f"group_sessions_per_user: false\n"
            f"memory:\n"
            f"  memory_enabled: false\n"
            f"plugins:\n"
            f"  enabled:\n"
            f"    - band\n"
        )
        self.stack.up("gateway", build=True)
        # s6 cont-init (user remap, /opt/data chown) races the first exec —
        # poll the policy script until it lands rather than exec'ing once.
        # It is idempotent, so retries are harmless.
        wait_for(
            lambda: self._sh(
                f'{_VENV_PY} "{_SCRIPTS_DIR}/ensure_access_policy.py"', check=False
            ).returncode
            == 0,
            timeout_s=120.0,
            desc=f"hermes container init + access policy ({self.stack.project})",
        )
        self.stack.restart("gateway")

    def wait_ready(self) -> None:
        wait_for(
            self._gateway_verified,
            timeout_s=self.ready_timeout_s,
            desc=f"hermes gateway to verify against Band ({self.stack.project})",
        )

    def _gateway_verified(self) -> bool:
        result = self._sh(
            f'{_VENV_PY} "{_SCRIPTS_DIR}/verify_gateway.py"', check=False
        )
        if result.returncode != 0:
            return False
        return bool(json.loads(result.stdout).get("success"))

    def down(self) -> None:
        self.stack.down()

    def diagnostics(self) -> str:
        return (
            f"{super().diagnostics()}\n"
            f"{self.stack.ps()}\n{self.stack.logs('gateway')}"
        )

    def _sh(self, command: str, *, check: bool = True):
        """Run a shell line inside the gateway container as the hermes user."""
        return self.stack.exec(
            "gateway", "sh", "-lc", command, user="hermes", check=check
        )
