"""The runner contract every harness implements.

A harness's lifecycle, from the driver's point of view, is four verbs:

    up(identity)        start the stack, wired to a pre-provisioned Band agent
    wait_ready()        block until the agent is live on Band (or ReadyTimeout)
    attach_room(room)   make the harness serve a driver-created room (no-op for
                        harnesses that answer any room they're @mentioned in)
    down()              stop everything and remove local state

Identities are provisioned by the driver via the SDK toolkit's ResourceManager
and injected into each harness. A harness never registers its own agent here,
so Band-side teardown stays centralized in `reap_all()`.

Runners are synchronous because bring-up is subprocess orchestration
(`docker compose`, `exec`) called from session-scoped fixtures.
"""

from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, ClassVar

#: The checked-in per-harness deployment config (compose files, Dockerfiles).
STACKS_DIR = Path(__file__).resolve().parents[1] / "stacks"


@dataclass(frozen=True)
class BandIdentity:
    """A pre-provisioned Band agent, as handed to a harness.

    `handle` is the namespaced `owner_handle/agent_slug` form, read from
    GET /agent/me after registration. Other agents use it to @mention this one.
    """

    agent_id: str
    api_key: str
    name: str
    handle: str


@dataclass(frozen=True)
class HarnessContext:
    """Everything a runner needs beyond the identity itself.

    `llm_env` is passed through to the harness process (provider keys, model
    pins); harnesses ignore keys they don't use. `work_root` is a per-run
    scratch directory — each harness owns `work_root/<name>/`.
    """

    run_id: str
    band_base_url: str
    band_ws_url: str
    work_root: Path
    #: Model to pin on harnesses that need one configured explicitly
    #: (OpenClaw and Hermes have no runtime default model).
    anthropic_model: str = "claude-haiku-4-5"
    llm_env: dict[str, str] = field(default_factory=dict)


class ReadyTimeout(AssertionError):
    """A harness did not reach readiness within its bound.

    An AssertionError on purpose: in a conformance run "never came up" is a
    verdict about the harness, not test-infrastructure noise.
    """


class Harness(ABC):
    """Base runner. Subclasses implement the four lifecycle verbs."""

    name: ClassVar[str]

    #: Upper bound for wait_ready(); generous because first contact includes
    #: image cold-start work, but readiness is never assumed.
    ready_timeout_s: ClassVar[float] = 180.0

    def __init__(self, ctx: HarnessContext) -> None:
        self.ctx = ctx
        self.workdir = ctx.work_root / self.name
        self.workdir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def up(self, identity: BandIdentity) -> None:
        """Start the harness stack, configured for `identity`."""

    @abstractmethod
    def wait_ready(self) -> None:
        """Block until the agent is connected to Band; raise ReadyTimeout
        (with diagnostics) otherwise."""

    def attach_room(self, room_id: str) -> None:
        """Wire a driver-created room into the harness, if it needs that.

        Default: no-op. Hermes and OpenClaw serve any room the Band platform
        delivers mentions for; NanoClaw routes per registered messaging group
        and overrides this.
        """

    @abstractmethod
    def down(self) -> None:
        """Stop the stack and remove local state. Must be safe to call after
        a partial/failed up() — teardown always runs."""

    def diagnostics(self) -> str:
        """Best-effort state dump attached to failures. Subclasses extend."""
        return f"[{self.name}] workdir={self.workdir}"


def wait_for(
    probe: Callable[[], bool],
    *,
    timeout_s: float,
    interval_s: float = 3.0,
    desc: str,
) -> None:
    """Poll `probe` until it returns True; raise ReadyTimeout at the bound.

    A False return or an exception both count as "not yet" — probes may freely
    shell out to services that are still starting. The last failure is
    preserved on the ReadyTimeout for diagnosis.
    """
    deadline = time.monotonic() + timeout_s
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            if probe():
                return
            last_error = None
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            last_error = exc
        time.sleep(interval_s)
    detail = f": last error: {last_error}" if last_error else ""
    raise ReadyTimeout(f"timed out after {timeout_s:.0f}s waiting for {desc}{detail}")
