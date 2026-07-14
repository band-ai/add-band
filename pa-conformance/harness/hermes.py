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
from harness.contract import (
    STACKS_DIR,
    BandIdentity,
    Harness,
    ModelWire,
    Profile,
    Unknown,
    rewrite_env_value,
    wait_for,
)

_VENV_PY = "/opt/hermes/.venv/bin/python"

#: Locates the plugin's bundled add-band scripts inside the container.
_SCRIPTS_DIR = (
    f'$({_VENV_PY} -c "import hermes_band_platform as p, pathlib; '
    "print(pathlib.Path(p.__file__).parent / 'skills/add-band/scripts')\")"
)


class HermesHarness(Harness):
    name = "hermes"
    #: Only the gateway is bounced: everything Hermes persists lives in the
    #: $PA_HERMES_HOME bind mount, so a bounce always rehydrates from disk. The
    #: stand-in service (added by the stacks/standin/ fragment) is deliberately
    #: excluded, so its in-memory recording survives a restart — what the L4
    #: strict thread-recovery row reads across the bounce.
    restart_services = ("gateway",)
    profile = Profile(
        #: live wire 2026-07-12: band_send_message / band_create_room et al.
        #: beside native tools (browser_*, terminal, …) in the recorded
        #: ModelCall.tools
        tool_namespace="band_",
        #: live wire 2026-07-12: Hermes's own shell tool, in ModelCall.tools
        native_tool="terminal",
        hub_identity=Unknown.UNKNOWN,
        conversation_identity=Unknown.UNKNOWN,
        ordering_fallback=Unknown.UNKNOWN,
        idempotency_scheme=Unknown.UNKNOWN,
        #: live canary 2026-07-12: passthrough ModelCall recorded through the
        #: stand-in (upstream 200) and a scripted echo served + landed on Band
        model_wire=ModelWire.SUPPORTED,
        band_context_read=Unknown.UNKNOWN,
        non_owner_policy=Unknown.UNKNOWN,
        #: live: test_restart's exactly-once row waits on PROCESSED and
        #: passes on Hermes (2026-07-12)
        emits_processed=True,
        #: live 2026-07-12: verify_gateway.py (the readiness probe) reports the
        #: "Hermes Hub" room created + owner resolved on every bring-up
        provisions_hub=True,
        #: live 2026-07-12: test_thread_recovery_carries_prior_transcript
        #: passes — the post-restart model call carries the pre-restart marker
        rehydrates_thread_after_restart=True,
    )

    def __init__(self, ctx):
        super().__init__(ctx)
        self.home = self.workdir / "home"
        self._env_snapshot: str | None = None
        self.stack = ComposeStack(
            file=STACKS_DIR / "hermes" / "compose.yaml",
            project=f"pa-hermes-{ctx.run_id}",
            overrides=self.standin_overrides(),
            env={
                "PA_HERMES_HOME": str(self.home),
                "PA_UID": str(os.getuid()),
                "PA_GID": str(os.getgid()),
                # The plugin commit baked into the image (pin from pins.env).
                "BAND_HERMES_REF": pa_settings().band_hermes_ref,
                **ctx.llm_env,
                **self.standin_env(),
            },
        )
        # Provider keys ride the compose env; scrub them from any surfaced
        # output alongside the agent key registered in up(). The stand-in
        # control token is registered by up_standin() (base owns the secret).
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
        self.up_standin()
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

    def stop(self) -> None:
        """Halt the gateway, then reset its log: verify_gateway.py (the
        readiness probe) scans the tail of gateway.log for success patterns,
        and the log survives restarts on the bind mount — a past boot's
        "Connected as agent" line would satisfy readiness for the NEXT boot.
        Truncated while stopped so wait_ready() reflects only the current
        process; container-level diagnostics (docker logs) are unaffected."""
        super().stop()
        gateway_log = self.home / "logs" / "gateway.log"
        if gateway_log.exists():
            gateway_log.write_text("")

    def corrupt_platform_creds(self) -> None:
        self._env_snapshot = rewrite_env_value(
            self.home / ".env", "BAND_API_KEY", "pa-invalid-credential"
        )

    def restore_platform_creds(self) -> None:
        assert self._env_snapshot is not None, "corrupt_platform_creds() first"
        (self.home / ".env").write_text(self._env_snapshot)
        self._env_snapshot = None

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
