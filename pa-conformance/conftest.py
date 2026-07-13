"""PA conformance session wiring.

Replicates band-sdk-python's baseline fixture shape over the pytest-free
toolkit: settings, user REST client, WS observer, ResourceManager, and capture
factory. The PA layer adds session-scoped harnesses for
NanoClaw/OpenClaw/Hermes.

Harness selection: PA_HARNESSES=nanoclaw,openclaw,hermes (default: all).

Blocking bring-up work runs via asyncio.to_thread so the session WS observer's
heartbeats keep flowing while a stack builds/boots.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import AsyncGenerator, Awaitable, Sequence
from dataclasses import dataclass
from typing import Protocol

import pytest
from band_rest import AsyncRestClient

from band.client.streaming import WebSocketClient

from pa_settings import pa_settings
from driver.ops import PAUserOps
from driver.visibility import Seed, VisibilityOutcome, probe_history_visibility
from driver.sdk import (
    BaselineSettings,
    CaptureFactory,
    ProvisionedAgent,
    ResourceManager,
    TrackingWebSocketClient,
    agent_rest_client,
    new_run_id,
    reply_capture,
)
from harness import HARNESSES, BandIdentity, Harness, HarnessContext

logger = logging.getLogger(__name__)
_known_gap_xpasses: list[str] = []
_intermittent_gap_nodeids: set[str] = set()


def selected_harnesses() -> list[str]:
    names = list(pa_settings().pa_harnesses) or list(HARNESSES)
    unknown = sorted(set(names) - set(HARNESSES))
    if unknown:
        raise ValueError(f"unknown harness(es) {unknown}; known: {sorted(HARNESSES)}")
    return names


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    has_explicit_pa_name = any(
        marker.args
        and "pa_name" in {name.strip() for name in marker.args[0].split(",")}
        for marker in metafunc.definition.iter_markers("parametrize")
    )
    if "pa_name" in metafunc.fixturenames and not has_explicit_pa_name:
        metafunc.parametrize("pa_name", selected_harnesses())


def pytest_runtest_setup(item: pytest.Item) -> None:
    # Same gate as the SDK suite: this suite is live-only by definition.
    if not pa_settings().e2e_tests_enabled:
        pytest.skip("live suite — set E2E_TESTS_ENABLED=true to run")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Translate `@pytest.mark.known_gap(<harness>, reason=…)` into an xfail on
    that harness's parametrized instance only.

    A plain xfail decorator can't target one value of a dynamically generated
    param; this keeps known, ticketed per-harness conformance gaps declarative
    at the test. strict=False keeps unresolved upstream gaps from failing the
    suite; XPASS is promoted to a suite failure so the marker cannot mask a
    later regression. Other harnesses stay strict.

    `intermittent=True` declares a gap whose ticket documents it as
    non-deterministic: it xfails when it reproduces, and a passing run proves
    nothing, so its XPASS is not promoted to a suite failure. Only closing the
    ticket removes the marker.
    """
    for item in items:
        if gap := _known_gap(item):
            reason, intermittent = gap
            item.add_marker(pytest.mark.xfail(reason=reason, strict=False))
            if intermittent:
                _intermittent_gap_nodeids.add(item.nodeid)
        if reason := _harness_skip_reason(item):
            item.add_marker(pytest.mark.skip(reason=reason))


def _known_gap(item: pytest.Item) -> tuple[str, bool] | None:
    """The declared known_gap (reason, intermittent) for this item's harness.

    A pa_name-parametrized item gaps only its own instance. A test without a
    pa_name param exercises all selected harnesses in one item (e.g. the group
    fan-out), so its gap applies whenever the gapped harness participates in
    the run."""
    markers = list(item.iter_markers("known_gap"))
    for marker in markers:
        if not marker.args or len(marker.args) > 2:
            raise pytest.UsageError(
                f"{item.nodeid}: known_gap requires harness and reason"
            )
        harness = marker.args[0]
        positional_reason = marker.args[1] if len(marker.args) == 2 else None
        keyword_reason = marker.kwargs.get("reason")
        if positional_reason is not None and keyword_reason is not None:
            raise pytest.UsageError(
                f"{item.nodeid}: known_gap reason must be positional or keyword"
            )
        reason = keyword_reason if keyword_reason is not None else positional_reason
        if harness not in HARNESSES:
            raise pytest.UsageError(
                f"{item.nodeid}: unknown known_gap harness {harness!r}"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise pytest.UsageError(
                f"{item.nodeid}: known_gap requires a non-empty reason"
            )
        if not isinstance(marker.kwargs.get("intermittent", False), bool):
            raise pytest.UsageError(
                f"{item.nodeid}: known_gap intermittent must be a bool"
            )
    spec = getattr(item, "callspec", None)  # absent on unparametrized tests
    pa_name = spec.params.get("pa_name") if spec is not None else None
    for marker in markers:
        reason = marker.kwargs.get("reason")
        if reason is None and len(marker.args) == 2:
            reason = marker.args[1]
        harness = marker.args[0]
        if harness == pa_name or (
            pa_name is None and harness in selected_harnesses()
        ):
            return reason, marker.kwargs.get("intermittent", False)
    return None


def _harness_skip_reason(item: pytest.Item) -> str | None:
    """The declared harness-specific skip reason for this parametrized item."""
    spec = getattr(item, "callspec", None)
    if spec is None:
        return None
    skips = {
        skip.args[0]: skip.kwargs["reason"]
        for skip in item.iter_markers("harness_skip")
    }
    return skips.get(spec.params.get("pa_name"))


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Record known-gap XPASS results for the session exit policy."""
    if report.when == "call" and report.outcome == "passed" and getattr(
        report, "wasxfail", None
    ) and report.nodeid not in _intermittent_gap_nodeids:
        _known_gap_xpasses.append(report.nodeid)


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    if _known_gap_xpasses:
        terminalreporter.write_sep("!", "known-gap XPASS requires marker removal")
        for nodeid in _known_gap_xpasses:
            terminalreporter.write_line(nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _known_gap_xpasses:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@dataclass(frozen=True)
class PA:
    """A harness that is up and ready per its runner's readiness probe.

    Readiness is per-harness (only Hermes proves a Band round-trip at
    bring-up); Band-side proof of life is the L0a liveness scenario.
    """

    harness: Harness
    agent: ProvisionedAgent
    handle: str  # namespaced owner_handle/agent_slug — how others @mention it


class RoomFactory(Protocol):
    """Provision a room for these PAs and wire it into each of their harnesses."""

    def __call__(self, members: Sequence[PA], *, title: str) -> Awaitable[str]: ...


@pytest.fixture(scope="session")
def settings() -> BaselineSettings:
    s = BaselineSettings()
    assert s.credentials.api_key_user, "BAND_API_KEY_USER is required"
    return s


@pytest.fixture(scope="session")
def run_id() -> str:
    return new_run_id()


@pytest.fixture(scope="session")
def user_client(settings: BaselineSettings) -> AsyncRestClient:
    return AsyncRestClient(
        api_key=settings.credentials.api_key_user,
        base_url=settings.endpoints.rest_url,
    )


@pytest.fixture(scope="session")
async def band_ws(
    settings: BaselineSettings,
) -> AsyncGenerator[TrackingWebSocketClient, None]:
    ws = WebSocketClient(
        ws_url=settings.endpoints.ws_url,
        api_key=settings.credentials.api_key_user,
        agent_id=None,  # user connection, not an agent
    )
    async with ws:
        tracking = TrackingWebSocketClient(ws)
        yield tracking
        await tracking.cleanup_channels()


@pytest.fixture(scope="session")
async def resources(
    settings: BaselineSettings, user_client: AsyncRestClient, run_id: str
) -> AsyncGenerator[ResourceManager, None]:
    manager = ResourceManager(
        user_client=user_client, settings=settings, run_id=run_id
    )
    if settings.run.orphan_sweep:
        await manager.sweep_orphans()
    yield manager
    if settings.run.autoclean:
        await manager.reap_all()


@pytest.fixture(scope="session")
def user_ops(user_client: AsyncRestClient) -> PAUserOps:
    return PAUserOps(user_client)


@pytest.fixture(scope="session")
def capture(
    band_ws: TrackingWebSocketClient,
    user_ops: PAUserOps,
    settings: BaselineSettings,
) -> CaptureFactory:
    return functools.partial(
        reply_capture,
        band_ws,
        user_ops=user_ops,
        settings=settings,
        deadline_s=float(settings.e2e_timeout),
    )


class VisibilityProbe(Protocol):
    """Seed a room per the cell's declared intent, then ask the reader what
    it can see."""

    def __call__(self, reader: str, seed: Seed) -> Awaitable[VisibilityOutcome]: ...


@pytest.fixture
def visibility_probe(
    pas: dict[str, PA],
    resources: ResourceManager,
    user_ops: PAUserOps,
    capture: CaptureFactory,
    run_id: str,
) -> VisibilityProbe:
    return functools.partial(
        probe_history_visibility,
        pas=pas,
        resources=resources,
        user_ops=user_ops,
        capture=capture,
        run_id=run_id,
    )


@pytest.fixture
def room_with(resources: ResourceManager) -> RoomFactory:
    """Provision a room for the given PAs and attach it to each harness.

    Folds the provision + per-harness attach_room that every scenario opens
    with. attach_room is sync (subprocess orchestration), so it runs in a thread
    to keep the session WS observer's heartbeats flowing.
    """

    async def _room(members: Sequence[PA], *, title: str) -> str:
        room_id = await resources.provision_room(
            title=title, participants=[m.agent.id for m in members]
        )
        for m in members:
            await asyncio.to_thread(m.harness.attach_room, room_id)
        return room_id

    return _room


@pytest.fixture(scope="session")
async def pas(
    settings: BaselineSettings,
    resources: ResourceManager,
    run_id: str,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> AsyncGenerator[dict[str, PA], None]:
    """Every selected harness, stood up on Band and keyed by name.

    Session-scoped: one concurrent bring-up per run. All bring-up failures are
    logged before the fixture raises; teardown always runs per harness.
    """
    ctx = HarnessContext(
        run_id=run_id,
        band_base_url=settings.endpoints.rest_url,
        band_ws_url=settings.endpoints.ws_url,
        work_root=tmp_path_factory.mktemp("pa"),
        anthropic_model=settings.llm_models.anthropic_model,
        llm_env=_llm_env(settings),
    )
    started: list[Harness] = []
    agents: list[ProvisionedAgent] = []
    live: dict[str, PA] = {}
    try:
        results = await asyncio.gather(
            *(
                _bring_up(name, ctx, resources, settings, started, agents)
                for name in selected_harnesses()
            ),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, Exception)]
        for failure in failures:
            logger.error(
                "bring-up failed",
                exc_info=(type(failure), failure, failure.__traceback__),
            )
        if failures:
            raise failures[0]
        for result in results:
            live[result.harness.name] = result
        yield live
    finally:
        await _teardown(
            started,
            agents,
            resources,
            settings,
            dump_diagnostics=bool(request.session.testsfailed),
        )


@pytest.fixture
def pa(pa_name: str, pas: dict[str, PA]) -> PA:
    return pas[pa_name]


async def _bring_up(
    name: str,
    ctx: HarnessContext,
    resources: ResourceManager,
    settings: BaselineSettings,
    started: list[Harness],
    agents: list[ProvisionedAgent],
) -> PA:
    """Provision the agent, start its harness, and block until it is live on
    Band. The harness and agent are appended to `started`/`agents` before
    anything can fail, so teardown always sees a partially-started stack AND
    reaps rooms of an agent whose harness never became ready (a harness can
    create its hub room and then fail readiness)."""
    agent = await resources.provision_agent(name)
    agents.append(agent)
    handle = await _agent_handle(agent, settings)
    harness = HARNESSES[name](ctx)
    started.append(harness)
    logger.info("bringing up %s as %s (@%s)", name, agent.name, handle)
    identity = BandIdentity(
        agent_id=agent.id, api_key=agent.api_key, name=agent.name, handle=handle
    )
    try:
        await asyncio.to_thread(harness.up, identity)
        await asyncio.to_thread(harness.wait_ready)
    except Exception as exc:
        raise RuntimeError(
            f"{name} failed to come up: {exc}\n{harness.diagnostics()}"
        ) from exc
    return PA(harness=harness, agent=agent, handle=handle)


async def _teardown(
    started: list[Harness],
    agents: list[ProvisionedAgent],
    resources: ResourceManager,
    settings: BaselineSettings,
    *,
    dump_diagnostics: bool,
) -> None:
    """Best-effort teardown: optionally dump diagnostics, stop every stack, then
    reap the rooms each agent is in."""
    # Harness readiness is local-only for some harnesses (NanoClaw), so a PA
    # that never reaches Band fails tests, not bring-up — the stack logs
    # captured here, while the stacks are still up, are the only runtime
    # evidence.
    def log_failure(action: str, harness: Harness, failure: Exception) -> None:
        logger.error(
            "%s of %s failed",
            action,
            harness.name,
            exc_info=(type(failure), failure, failure.__traceback__),
        )

    if dump_diagnostics:
        diagnostics = await asyncio.gather(
            *(asyncio.to_thread(harness.diagnostics) for harness in started),
            return_exceptions=True,
        )
        for harness, result in zip(started, diagnostics):
            if isinstance(result, Exception):
                log_failure("diagnostics", harness, result)
            else:
                logger.info("%s diagnostics before teardown:\n%s", harness.name, result)
    teardown = await asyncio.gather(
        *(asyncio.to_thread(harness.down) for harness in started),
        return_exceptions=True,
    )
    for harness, result in zip(started, teardown):
        if isinstance(result, Exception):
            log_failure("teardown", harness, result)
    # Reap every room each agent is in: driver-provisioned rooms and rooms the
    # agent created on its own (owner hubs). Iterates every PROVISIONED agent,
    # not just the live PAs — a harness that failed readiness may still have
    # created its hub room. reap_room keeps the ResourceManager ledger
    # consistent, so the later reap_all never double-deletes. Must run while
    # the agents still exist (the listing is agent-authenticated).
    for agent in agents:
        try:
            for room_id in await _agent_room_ids(agent, settings):
                await resources.reap_room(room_id)
        except Exception:
            logger.exception("room cleanup for %s failed", agent.name)


async def _agent_handle(agent: ProvisionedAgent, settings: BaselineSettings) -> str:
    """The namespaced handle is not in the register response — it has to be
    read back from the identity endpoint, as the agent."""
    me = (await agent_rest_client(agent, settings).agent_api_identity.get_agent_me()).data
    assert me.handle, f"agent {agent.id} has no handle"
    return me.handle


async def _agent_room_ids(
    agent: ProvisionedAgent, settings: BaselineSettings
) -> list[str]:
    """Rooms the agent participates in, read with the agent's own key."""
    response = await agent_rest_client(agent, settings).agent_api_chats.list_agent_chats()
    return [room.id for room in response.data or []]


def _llm_env(settings: BaselineSettings) -> dict[str, str]:
    env = {
        "ANTHROPIC_API_KEY": settings.llm_credentials.anthropic_api_key,
        "OPENAI_API_KEY": settings.llm_credentials.openai_api_key,
    }
    return {k: v for k, v in env.items() if v}
