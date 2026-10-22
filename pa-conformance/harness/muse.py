"""Muse runner.

Muse is ephemeral — there is no persistent agent runtime. The "harness"
is the push bridge daemon (muse/bridge_daemon.py): it holds a WebSocket
open, writes inbound messages to the inbox, and sends via the REST API.

Bring-up is minimal:
  - `up()`: write the injected identity to the compose env, start the stack
  - `wait_ready()`: block until the bridge's /tmp/bridge-ready file exists
    (touched on successful WebSocket connect)
  - `attach_room()`: no-op — the bridge auto-subscribes to all agent rooms
  - `down()`: stop the stack and remove the state dir

There is no model, no gateway, no conversation state. The Profile reflects
this: Muse does not answer mentions, it bridges them.
"""

from __future__ import annotations

from harness.compose import ComposeStack
from harness.contract import (
    STACKS_DIR,
    BandIdentity,
    Harness,
    HarnessContext,
    ModelWire,
    Profile,
    Unknown,
    wait_for,
)


class MuseHarness(Harness):
    name = "muse"
    restart_services = ("bridge",)
    profile = Profile(
        # Muse has no model — it's a bridge, not a conversational agent.
        # Unvalidated facts are UNKNOWN, not blank.
        tool_namespace=Unknown.UNKNOWN,
        native_tool=Unknown.UNKNOWN,
        hub_identity=Unknown.UNKNOWN,
        conversation_identity=Unknown.UNKNOWN,
        ordering_fallback=Unknown.UNKNOWN,
        idempotency_scheme=Unknown.UNKNOWN,
        model_wire=ModelWire.UNSUPPORTED,
        band_context_read=Unknown.UNKNOWN,
        non_owner_policy=Unknown.UNKNOWN,
        emits_processed=False,
        provisions_hub=False,
        rehydrates_thread_after_restart=False,
        #: muse/bridge_daemon.py:85 (on_message): inbound events are written
        #: to the inbox and the wake pipe — no code path posts a reply
        answers_mentions=False,
    )

    def __init__(self, ctx: HarnessContext):
        super().__init__(ctx)
        self.stack = ComposeStack(
            file=STACKS_DIR / "muse" / "compose.yaml",
            project=f"pa-muse-{ctx.run_id}",
        )

    def up(self, identity: BandIdentity) -> None:
        """Start the bridge, wired to the injected Band agent identity."""
        # The compose file reads these from the stack env
        self.stack.env.update({
            "BAND_AGENT_ID": identity.agent_id,
            "BAND_API_KEY": identity.api_key,
            "BAND_BASE_URL": self.ctx.band_base_url,
            "PA_MUSE_HOME": str(self.workdir),
        })
        self.stack.up()

    def wait_ready(self) -> None:
        """Block until the bridge signals WebSocket connect."""
        def _ready() -> bool:
            # The bridge touches /tmp/bridge-ready in the container on connect.
            # We check via docker exec.
            try:
                self.stack.exec("bridge", "test", "-f", "/tmp/bridge-ready")
                return True
            except Exception:
                return False

        wait_for(_ready, timeout_s=60, desc="muse bridge ready")

    def down(self) -> None:
        """Stop the stack and remove local state."""
        self.stack.down()
