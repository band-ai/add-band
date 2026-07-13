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
import secrets

from pa_settings import pa_settings

from harness.compose import ComposeStack
from harness.contract import STACKS_DIR, BandIdentity, Harness, wait_for

_CHANNEL = "openclaw-channel-band"


class OpenClawHarness(Harness):
    name = "openclaw"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.stack = ComposeStack(
            file=STACKS_DIR / "openclaw" / "compose.yaml",
            project=f"pa-openclaw-{ctx.run_id}",
            env=dict(ctx.llm_env),
        )
        # Provider keys ride the compose env; scrub them from any surfaced
        # output alongside the run secrets registered in up().
        self.stack.redactions |= set(ctx.llm_env.values())
        self._account_id: str | None = None

    def up(self, identity: BandIdentity) -> None:
        self._account_id = identity.agent_id
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
        self.stack.up("gateway")

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
