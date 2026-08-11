"""The runner contract every harness implements.

A harness's lifecycle, from the driver's point of view, is four verbs:

    up(identity)        start the stack, wired to a pre-provisioned Band agent
    wait_ready()        block until the runner's readiness probe passes
                        (or ReadyTimeout)
    attach_room(room)   make the harness serve a driver-created room (no-op for
                        harnesses that answer any room they're @mentioned in)
    down()              stop everything and remove local state

Restart verbs (L4 restart/rehydration) bounce the PA runtime while its
persisted store survives — the opposite of down()/up(), which wipe and
re-provision:

    stop()              halt the runtime service(s); datastores stay up
    start()             resume against the preserved store — a faithful
                        process cold-start, nothing re-seeded or re-minted
    restart()           stop() then start(); callers re-run wait_ready(),
                        mirroring up()/wait_ready()

corrupt_platform_creds()/restore_platform_creds() are the degraded-state
fixture: invalidate the persisted Band credentials in place while stopped,
then hand back a healthy store (harnesses are session-scoped and shared).

Identities are provisioned by the driver via the SDK toolkit's ResourceManager
and injected into each harness. A harness never registers its own agent here,
so Band-side teardown stays centralized in `reap_all()`.

Runners are synchronous because bring-up is subprocess orchestration
(`docker compose`, `exec`) called from session-scoped fixtures.
"""

from __future__ import annotations

import enum
import functools
import json
import re
import secrets
import subprocess
import time
import types
import typing
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Callable, ClassVar

from pa_settings import pa_settings

from harness.compose import ComposeError

if TYPE_CHECKING:
    from harness.compose import ComposeStack

#: The checked-in per-harness deployment config (compose files, Dockerfiles).
STACKS_DIR = Path(__file__).resolve().parents[1] / "stacks"

#: Container ports the model stand-in serves (stacks/standin/server.py):
#: the model seam harnesses point ANTHROPIC_BASE_URL at, and the driver's
#: authenticated control API (published dynamically per stack).
STANDIN_MODEL_PORT = 8080
STANDIN_CONTROL_PORT = 8081


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


class Unknown(enum.Enum):
    """Declared ignorance about a conformance fact — distinct from a guessed
    default or a silent absence. Rows gated on an UNKNOWN field skip
    declaratively (the `requires_profile` marker) instead of asserting on a
    fact nobody validated."""

    UNKNOWN = "unknown"

class ModelWire(enum.Enum):
    """Whether the harness's model calls can be routed through the stand-in.

    Settled by the Phase B canary, never inferred: SUPPORTED requires a
    recorded canary ModelCall; UNSUPPORTED is the explicit verdict when the
    probe shows the base-url env ignored. No silent third state — UNKNOWN
    means "not yet probed" and gates T1 rows exactly like UNSUPPORTED.
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Profile:
    """Facts a conformance row needs that the code can't discover at runtime.

    Every field is either a validated fact — with an adjacent ``#:`` comment
    at the declaration naming its evidence (a live test/date or an upstream
    ``file:line``; AGENTS.md rule) — or UNKNOWN. Boolean facts are
    ``bool | Unknown`` so a harness can declare ignorance instead of a guessed
    default. Rows gated on a missing fact skip declaratively via the
    ``requires_profile`` marker.
    """

    tool_namespace: str | Unknown  # Band tool-name prefix, e.g. "band_"
    native_tool: str | Unknown  # a representative native (non-Band) tool name
    hub_identity: str | Unknown  # how the owner hub is identified/persisted
    conversation_identity: str | Unknown  # room→session key (per-room, per-user, …)
    ordering_fallback: str | Unknown  # declared ordering when server order breaks
    idempotency_scheme: str | Unknown  # message/command/tool-call dedupe scheme
    model_wire: ModelWire  # stand-in routing capability (Phase B verdict)
    band_context_read: bool | Unknown  # get_agent_chat_context meaningful here
    non_owner_policy: str | Unknown  # refuse / ignore / serve (commands vs prompts)
    emits_processed: bool | Unknown  # PROCESSED delivery status on Band
    provisions_hub: bool | Unknown  # published path creates an owner hub room
    #: post-restart model context carries the pre-restart transcript (eager
    #: thread replay) — the strict L4 thread-recovery row's read point
    rehydrates_thread_after_restart: bool | Unknown

    def __post_init__(self) -> None:
        for spec in fields(self):
            value = getattr(self, spec.name)
            if not isinstance(value, _profile_field_types()[spec.name]):
                raise TypeError(
                    f"profile field {spec.name} holds {value!r} — declare a "
                    "validated fact of the annotated type, or UNKNOWN"
                )
            if isinstance(value, str) and not value.strip():
                raise ValueError(
                    f"profile field {spec.name} is an empty string — an "
                    "unvalidated fact is UNKNOWN, not blank"
                )

    def satisfied(self, field_name: str) -> bool:
        """Whether rows gated on `field_name` may run: a validated positive
        fact passes; declared ignorance and negative verdicts skip
        declaratively."""
        value = getattr(self, field_name)
        if value is Unknown.UNKNOWN:
            return False
        if value in (ModelWire.UNKNOWN, ModelWire.UNSUPPORTED):
            return False
        return value is not False  # non-empty strings guarded in __post_init__

    def describe(self, field_name: str) -> str:
        """The declared value, rendered for a skip reason."""
        value = getattr(self, field_name)
        return value.value if isinstance(value, enum.Enum) else repr(value)


#: The declared field names — what `requires_profile` markers may name.
PROFILE_FIELDS = frozenset(spec.name for spec in fields(Profile))

#: Field references for marker call sites, generated from the dataclass so
#: there is exactly one source of field names:
#: `@pytest.mark.requires_profile(PROFILE_FIELD.emits_processed)`. A typo
#: fails at import (AttributeError), not at collection.
PROFILE_FIELD = types.SimpleNamespace(**{name: name for name in PROFILE_FIELDS})


@functools.lru_cache(maxsize=1)
def _profile_field_types() -> dict[str, tuple[type, ...]]:
    """Each Profile field's permitted runtime types, resolved from the
    dataclass annotations — the annotation is the single source of truth for
    what __post_init__ accepts."""
    hints = typing.get_type_hints(Profile)
    return {
        name: typing.get_args(hint) or (hint,) for name, hint in hints.items()
    }


class ReadyTimeout(AssertionError):
    """A harness did not reach readiness within its bound.

    An AssertionError on purpose: in a conformance run "never came up" is a
    verdict about the harness, not test-infrastructure noise.
    """


class Harness(ABC):
    """Base runner. Subclasses implement the four lifecycle verbs."""

    name: ClassVar[str]

    #: The harness's declared conformance facts. No default on purpose: a
    #: harness without a Profile fails the registry's import-time check
    #: (harness/__init__.py) before anything can collect.
    profile: ClassVar[Profile]

    #: Upper bound for wait_ready(); generous because first contact includes
    #: image cold-start work, but readiness is never assumed.
    ready_timeout_s: ClassVar[float] = 180.0

    #: The compose service(s) stop()/start() bounce — the PA runtime that
    #: connects to Band and rehydrates. Keeping datastore services out of this
    #: tuple is what makes a restart exercise rehydration rather than
    #: re-initialization; () bounces the whole stack.
    restart_services: ClassVar[tuple[str, ...]] = ()

    #: Every subclass constructs its ComposeStack; the base restart verbs
    #: drive it directly.
    stack: ComposeStack

    def __init__(self, ctx: HarnessContext) -> None:
        self.ctx = ctx
        self.workdir = ctx.work_root / self.name
        self.workdir.mkdir(parents=True, exist_ok=True)
        #: Per-run secret for the stand-in's control API — minted here, dies
        #: with the run (`down -v`; the stand-in holds it in memory only).
        #: None means PA_STANDIN=off: the standin service is never added to the
        #: stack and models are reached directly (no stand-in in the path).
        self.standin_control_token: str | None = (
            secrets.token_hex(16) if pa_settings().pa_standin else None
        )

    def standin_env(self) -> dict[str, str]:
        """Compose env that wires the stand-in into this stack: the control
        secret, the base URL that puts it in the harness's model path, and the
        image's build context. {} when disabled — with the standin compose
        fragment also absent (standin_overrides), the service simply does not
        exist. Subclasses spread this into their ComposeStack env."""
        if self.standin_control_token is None:
            return {}
        return {
            "PA_STANDIN_CONTROL_TOKEN": self.standin_control_token,
            "PA_STANDIN_DIR": str(STACKS_DIR / "standin"),
            "PA_MODEL_MODE": pa_settings().pa_model_mode.value,
            "ANTHROPIC_BASE_URL": f"http://standin:{STANDIN_MODEL_PORT}",
        }

    def standin_overrides(self) -> tuple[Path, ...]:
        """The stand-in compose fragment (`-f`) when enabled, else () — so
        PA_STANDIN=off means the service genuinely does not exist rather than a
        token-less container crash-looping. Subclasses fold this into their
        ComposeStack `overrides`."""
        if self.standin_control_token is None:
            return ()
        return (STACKS_DIR / "standin" / "compose.yaml",)

    def up_standin(self) -> None:
        """Build + start the stand-in and block until its control API answers;
        no-op when disabled. Runs before the harness's own runtime starts, so
        the first model call already finds its path in place. Registers the
        control token for redaction here — the base owns the secret, so no
        subclass can forget to scrub it."""
        if self.standin_control_token is None:
            return
        self.stack.redactions.add(self.standin_control_token)
        self.stack.up("standin", build=True)
        wait_for(
            self._standin_healthy,
            timeout_s=60.0,
            desc=f"model stand-in control API ({self.stack.project})",
        )

    def standin_control_port(self) -> int:
        """Host port of the stand-in's control API. Resolved fresh on each call
        (not cached): a later unscoped `stack.up()` — NanoClaw brings up its
        whole stack after up_standin() — can recreate the standin container and
        publish it on a new host port, so the current mapping is the only
        reliable one. `compose port` is cheap enough for the health poll and the
        single per-run read the driver client makes."""
        return self.stack.port("standin", STANDIN_CONTROL_PORT)

    def _standin_healthy(self) -> bool:
        try:
            port = self.standin_control_port()
        except ComposeError:
            return False  # port not published yet — keep polling
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/control/healthz",
            headers={"X-Control-Token": self.standin_control_token},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return bool(json.load(response).get("status") == "ok")

    @abstractmethod
    def up(self, identity: BandIdentity) -> None:
        """Start the harness stack, configured for `identity`."""

    @abstractmethod
    def wait_ready(self) -> None:
        """Block until the runner's readiness probe passes; raise ReadyTimeout
        otherwise.

        Readiness is the strongest signal each harness exposes, and it is NOT
        uniformly "connected to Band": Hermes proves a real Band round-trip,
        OpenClaw its channel account running, NanoClaw only its host serving
        locally. Band-side proof of life is the L0a liveness scenario — don't
        infer Band reachability from this returning.
        """

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

    def stop(self) -> None:
        """Halt the PA runtime service(s); datastores stay up and the
        persisted store is left intact (contrast down(), which wipes it)."""
        self.stack.stop(*self.restart_services)

    def start(self) -> None:
        """Resume the halted runtime against its preserved store — a faithful
        process cold-start: no secrets re-minted, nothing re-provisioned, no
        in-memory carryover."""
        self.stack.start(*self.restart_services)

    def restart(self) -> None:
        """stop() then start(). Callers re-run wait_ready() afterwards —
        readiness stays a separate verb, mirroring up()/wait_ready()."""
        self.stop()
        self.start()

    def corrupt_platform_creds(self) -> None:
        """Invalidate the persisted Band credentials in place, while stopped —
        the degraded-state fixture. Not every harness has one yet."""
        raise NotImplementedError(f"{self.name} has no degraded-creds fixture")

    def restore_platform_creds(self) -> None:
        """Undo corrupt_platform_creds(). Required whenever corruption is
        exercised: harnesses are session-scoped and shared, so a degraded-state
        check must hand back a healthy store."""
        raise NotImplementedError(f"{self.name} has no degraded-creds fixture")

    def onboard_via_bootstrap(self, *, user_api_key: str, agent_name: str) -> str:
        """Onboard the way a real user does — run the catalog's published
        bootstrap for this harness verbatim, which mints its own Band agent
        from the user key — and leave the runtime serving. Returns the minted
        agent id (the caller owns reaping it). The F4 alternative to
        up(identity); a fresh, dedicated harness instance only — never the
        session-shared one. Only harnesses whose published path runs headlessly
        implement it (Hermes and NanoClaw hand off to interactive AI sessions)."""
        raise NotImplementedError(
            f"{self.name}'s published onboarding path is not headless"
        )

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
    shell out to services that are still starting. The most recent exception is
    preserved on the ReadyTimeout for diagnosis; a later plain False does not
    clear it (an intermittently-raising probe would otherwise time out with no
    detail at all).
    """
    deadline = time.monotonic() + timeout_s
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except (ComposeError, subprocess.SubprocessError, OSError, ValueError) as exc:
            last_error = exc
        time.sleep(interval_s)
    detail = f": last error: {last_error}" if last_error else ""
    raise ReadyTimeout(f"timed out after {timeout_s:.0f}s waiting for {desc}{detail}")


def rewrite_env_value(file: Path, key: str, value: str) -> str:
    """Point `key` at `value` in a dotenv file and return the previous file
    content — the caller's restore snapshot.

    The rewrite is an in-place write_text: it keeps the file's inode, which a
    file bind mount (NanoClaw's /app/.env) tracks — writing a replacement file
    would detach the mount and the container would keep the old content.
    """
    original = file.read_text()
    assert re.search(rf"(?m)^{re.escape(key)}=", original), (
        f"{key} not present in {file}"
    )
    replacement = f"{key}={value}"
    file.write_text(
        re.sub(rf"(?m)^{re.escape(key)}=.*$", lambda _: replacement, original)
    )
    return original
