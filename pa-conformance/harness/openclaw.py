"""OpenClaw runner.

Bring-up follows add-band/openclaw/bootstrap.sh (this repo), headless form.
`gateway.mode local` is required for a fresh state dir, and the account's
wsUrl/restUrl must be persisted because the Band plugin manifest carries
production defaults.

All configuration happens before the gateway starts, using one-shot
`compose run` containers that write openclaw.json. Registration is skipped:
the driver injects a pre-provisioned
identity via `channels add --account <id> --token <key>`.

Readiness is two-stage: /readyz (gateway up), then the RPC health snapshot
reporting the Band channel account `connected` (agent live on Band).
"""

from __future__ import annotations

import json
import re
import secrets

from pa_settings import pa_settings

from harness.compose import ComposeStack
from harness.contract import (
    STACKS_DIR,
    BandIdentity,
    Harness,
    ModelWire,
    Profile,
    Unknown,
    wait_for,
)

_CHANNEL = "openclaw-channel-band"

#: The catalog's published onboarding script (repo root openclaw/bootstrap.sh),
#: run VERBATIM by onboard_via_bootstrap — conformance is about what users get.
_PUBLISHED_BOOTSTRAP = STACKS_DIR.parents[1] / "openclaw" / "bootstrap.sh"


class OpenClawHarness(Harness):
    name = "openclaw"
    #: Only the gateway is bounced: openclaw.json (auth token, channel account,
    #: model pin) lives in the `state` named volume, so a bounce rehydrates
    #: from it; up()'s seeding is never re-run (it would re-mint the token).
    #: The stand-in service (added by the stacks/standin/ fragment) is
    #: deliberately excluded, so its in-memory recording survives the restart.
    restart_services = ("gateway",)
    profile = Profile(
        #: live wire 2026-07-12: band_send_event / band_create_chatroom et
        #: al. beside native tools (message, exec, …) in the recorded
        #: ModelCall.tools
        tool_namespace="band_",
        #: live wire 2026-07-12: OpenClaw's own shell tool, in ModelCall.tools
        native_tool="exec",
        hub_identity=Unknown.UNKNOWN,
        conversation_identity=Unknown.UNKNOWN,
        ordering_fallback=Unknown.UNKNOWN,
        idempotency_scheme=Unknown.UNKNOWN,
        #: live canary 2026-07-12: passthrough ModelCall recorded through the
        #: stand-in (upstream 200) and a scripted echo served + landed on
        #: Band — via models.providers.anthropic.baseUrl (the built-in
        #: catalog hardcodes each model's baseUrl over ANTHROPIC_BASE_URL)
        model_wire=ModelWire.SUPPORTED,
        band_context_read=Unknown.UNKNOWN,
        non_owner_policy=Unknown.UNKNOWN,
        #: live: the channel plugin's delivery statuses stay `none` even
        #: after it visibly replies (driver/waits.py doctrine, 2026-07-11)
        emits_processed=False,
        #: live 2026-07-12: the published onboard provisions no hub room
        #: (onboard_via_bootstrap / tests/test_onboarding.py)
        provisions_hub=False,
        #: live 2026-07-12: after a gateway restart the next model call carries
        #: only the new turn (n_msgs=1, no prior transcript, no history/memory
        #: tool call) — OpenClaw does not replay the conversation into the
        #: post-restart model context
        rehydrates_thread_after_restart=False,
    )

    def __init__(self, ctx):
        super().__init__(ctx)
        self.stack = ComposeStack(
            file=STACKS_DIR / "openclaw" / "compose.yaml",
            project=f"pa-openclaw-{ctx.run_id}",
            overrides=self.standin_overrides(),
            env={**ctx.llm_env, **self.standin_env()},
        )
        # Provider keys ride the compose env; scrub them from any surfaced
        # output alongside the run secrets registered in up(). The stand-in
        # control token is registered by up_standin() (base owns the secret).
        self.stack.redactions |= set(ctx.llm_env.values())
        self._account_id: str | None = None
        self._api_key: str | None = None

    def up(self, identity: BandIdentity) -> None:
        self._account_id = identity.agent_id
        self._api_key = identity.api_key
        account = f"channels.{_CHANNEL}.accounts.{identity.agent_id}"
        # Both land on CLI argv, so a failed config step would otherwise carry
        # them into the surfaced error — register them for redaction first.
        auth_token = secrets.token_hex(24)
        self.stack.redactions |= {identity.api_key, auth_token}
        # Pinned version — an unversioned install resolves npm's mutable `latest`,
        # so the plugin code could differ run to run on an unchanged catalog.
        plugin = f"@band-ai/{_CHANNEL}@{pa_settings().openclaw_channel_version}"
        self._cli_offline("plugins", "install", plugin, "--force")
        self._cli_offline("config", "set", "gateway.mode", "local")
        # Without a persisted token the gateway mints a random one per startup
        # and the exec'd CLI can't authenticate to its RPC, so `gateway call
        # health` (the readiness probe) is rejected. Run-scoped value;
        # it never leaves the state volume.
        self._cli_offline("config", "set", "gateway.auth.mode", "token")
        self._cli_offline("config", "set", "gateway.auth.token", auth_token)
        self._cli_offline(
            "channels", "add",
            "--channel", _CHANNEL,
            "--account", identity.agent_id,
            "--token", identity.api_key,
        )
        self._cli_offline("config", "set", f"{account}.agentId", identity.agent_id)
        self._cli_offline("config", "set", f"{account}.restUrl", self.ctx.band_base_url)
        self._cli_offline("config", "set", f"{account}.wsUrl", self.ctx.band_ws_url)
        # OpenClaw has no default model; the key comes from the gateway env
        # (ANTHROPIC_API_KEY in the compose file), the pin from config.
        self._cli_offline(
            "config", "set",
            "agents.defaults.model.primary",
            f"anthropic/{self.ctx.anthropic_model}",
        )
        self._route_model_through_standin()
        self.up_standin()
        self.stack.up("gateway")

    def _route_model_through_standin(self) -> None:
        """Point the anthropic provider at the stand-in, if enabled. OpenClaw's
        built-in anthropic catalog hardcodes each model's baseUrl
        (register.runtime: `baseUrl: "https://api.anthropic.com"`), which wins
        over ANTHROPIC_BASE_URL in resolveAnthropicBaseUrl — so routing goes
        through OpenClaw's own custom-endpoint config surface instead
        (models.providers.<id>, the documented knob for self-hosted providers).
        Both bring-up paths (up() and onboard_via_bootstrap) call this, so the
        env var alone never silently leaves an instance unrouted."""
        if standin_base_url := self.standin_env().get("ANTHROPIC_BASE_URL"):
            self._cli_offline(
                "config", "set",
                "models.providers.anthropic.baseUrl", standin_base_url,
            )

    def wait_ready(self) -> None:
        wait_for(
            self._gateway_live,
            timeout_s=self.ready_timeout_s,
            desc=f"openclaw /readyz ({self.stack.project})",
        )
        wait_for(
            self._band_channel_connected,
            timeout_s=self.ready_timeout_s,
            desc=f"openclaw Band channel account to connect ({self.stack.project})",
        )

    def _gateway_live(self) -> bool:
        result = self.stack.exec(
            "gateway", "node", "-e",
            "fetch('http://127.0.0.1:18789/readyz')"
            ".then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))",
            check=False,
        )
        return result.returncode == 0

    def _band_channel_connected(self) -> bool:
        result = self._cli_live("gateway", "call", "health", "--json", check=False)
        if result.returncode != 0:
            return False
        health = json.loads(result.stdout)
        account = (
            health.get("channels", {})
            .get(_CHANNEL, {})
            .get("accounts", {})
            .get(self._account_id, {})
        )
        # The cached snapshot reports `running` (with `reconnectAttempts`);
        # `connected` only appears on deep probes — accept either. The Band
        # round-trip itself is proven by the liveness test, not this gate.
        return bool(account.get("connected") or account.get("running"))

    def onboard_via_bootstrap(self, *, user_api_key: str, agent_name: str) -> str:
        """Run openclaw/bootstrap.sh verbatim in the gateway image against
        this stack's state volume, then start the service on the state it
        produced (F4: following the guide reaches a serving agent).

        The script targets an already-working OpenClaw install and never
        configures a model, so that precondition is seeded first. It installs
        the channel plugin UNPINNED — the guide's reality; upstream drift
        surfaces here first, by design. Its trailing `openclaw gateway
        restart` manages a daemon inside the one-shot container, which exits
        with it. The script persists no `gateway.auth.token` (the service
        mints a random one per boot), so readiness here is /readyz only —
        the RPC health probe can't authenticate; "connected" is proven by
        the caller's live reply, and the published path provisions no hub.
        """
        self.stack.redactions.add(user_api_key)
        self._cli_offline(
            "config", "set",
            "agents.defaults.model.primary",
            f"anthropic/{self.ctx.anthropic_model}",
        )
        result = self.stack.run(
            "gateway", "-c", _PUBLISHED_BOOTSTRAP.read_text(),
            entrypoint="bash",
            env={
                "BAND_API_KEY": user_api_key,
                "BAND_AGENT_NAME": agent_name,
                "BAND_AGENT_DESCRIPTION": "PA conformance F4 onboarding check",
                "BAND_BASE_URL": self.ctx.band_base_url,
                "BAND_WS_URL": self.ctx.band_ws_url,
            },
        )
        registered = re.search(r"Registered agent (\S+)\.", result.stdout)
        assert registered, (
            f"bootstrap.sh did not report a registered agent:\n"
            f"{self.stack.scrub(result.stdout[-800:])}"
        )
        self._account_id = registered.group(1)
        # Route this instance's model calls through the stand-in the same way
        # up() does — the env var alone is ignored by the built-in catalog.
        self._route_model_through_standin()
        self.up_standin()
        self.stack.up("gateway")
        wait_for(
            self._gateway_live,
            timeout_s=self.ready_timeout_s,
            desc=f"openclaw /readyz after published onboard ({self.stack.project})",
        )
        return self._account_id

    def corrupt_platform_creds(self) -> None:
        self._set_channel_token("pa-invalid-credential")

    def restore_platform_creds(self) -> None:
        assert self._api_key is not None, "corrupt_platform_creds() first"
        self._set_channel_token(self._api_key)

    def _set_channel_token(self, token: str) -> None:
        """Point the persisted Band channel account at `token`. `channels add
        --token` persists the credential as the account's `apiKey` (probed
        live; `config get` redacts the value). Offline CLI: the verb runs
        against the state volume while the gateway is stopped."""
        self._cli_offline(
            "config", "set",
            f"channels.{_CHANNEL}.accounts.{self._account_id}.apiKey",
            token,
        )

    def down(self) -> None:
        self.stack.down()

    def diagnostics(self) -> str:
        return (
            f"{super().diagnostics()}\n"
            f"{self.stack.ps()}\n{self.stack.logs('gateway')}"
        )

    def _cli_offline(self, *argv: str):
        """CLI against the state volume only — must not need (or start) the
        gateway. openclaw's own docs use this shape for headless onboarding."""
        return self.stack.run("gateway", "dist/index.js", *argv, entrypoint="node")

    def _cli_live(self, *argv: str, check: bool = True):
        """CLI against the RUNNING gateway (same container, same netns)."""
        return self.stack.exec(
            "gateway", "node", "dist/index.js", *argv, check=check
        )
