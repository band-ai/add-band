"""Phase-0 session wiring.

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
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
from band_rest import AsyncRestClient

from band.client.streaming import WebSocketClient

from pa_settings import pa_settings
from driver.ops import PAUserOps
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


def selected_harnesses() -> list[str]:
    names = list(pa_settings().pa_harnesses) or list(HARNESSES)
    unknown = sorted(set(names) - set(HARNESSES))
    if unknown:
        raise ValueError(f"unknown harness(es) {unknown}; known: {sorted(HARNESSES)}")
    return names


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "pa_name" in metafunc.fixturenames:
        metafunc.parametrize("pa_name", selected_harnesses())


def pytest_runtest_setup(item: pytest.Item) -> None:
    # Same gate as the SDK suite: this suite is live-only by definition.
    if not pa_settings().e2e_tests_enabled:
        pytest.skip("live suite — set E2E_TESTS_ENABLED=true to run")


# Whether any test failed, so the session teardown knows to dump harness
# diagnostics while the stacks are still up. Harness readiness is local-only
# for some harnesses (NanoClaw), so a PA that never reaches Band fails tests,
# not bring-up — the stack logs at teardown are the only runtime evidence.
_session_failed = False


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    if report.failed:
        global _session_failed
        _session_failed = True
    return report


@dataclass(frozen=True)
class PA:
    """A harness that is up, ready, and reachable on Band."""

    harness: Harness
    agent: ProvisionedAgent
    handle: str  # namespaced owner_handle/agent_slug — how others @mention it


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


@pytest.fixture(scope="session")
async def pas(
    settings: BaselineSettings,
    resources: ResourceManager,
    run_id: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncGenerator[dict[str, PA], None]:
    """Stand up every selected harness; tear all of them down, always.

    Bring-up is fail-fast and includes harness diagnostics. Teardown is
    best-effort per harness. Rooms the agents created on their own (e.g. owner
    hubs) are adopted into the ResourceManager before it reaps.
    """
    ctx = HarnessContext(
        run_id=run_id,
        band_base_url=settings.endpoints.rest_url,
        band_ws_url=settings.endpoints.ws_url,
        work_root=tmp_path_factory.mktemp("pa"),
        anthropic_model=settings.llm_models.anthropic_model,
        llm_env=_llm_env(settings),
    )
    live: dict[str, PA] = {}
    started: list[Harness] = []
    try:
        for name in selected_harnesses():
            agent = await resources.provision_agent(name)
            handle = await _agent_handle(agent, settings)
            harness = HARNESSES[name](ctx)
            identity = BandIdentity(
                agent_id=agent.id,
                api_key=agent.api_key,
                name=agent.name,
                handle=handle,
            )
            started.append(harness)
            logger.info("bringing up %s as %s (@%s)", name, agent.name, handle)
            try:
                await asyncio.to_thread(harness.up, identity)
                await asyncio.to_thread(harness.wait_ready)
            except Exception as exc:
                raise RuntimeError(
                    f"{name} failed to come up: {exc}\n{harness.diagnostics()}"
                ) from exc
            live[name] = PA(harness=harness, agent=agent, handle=handle)
        yield live
    finally:
        if _session_failed:
            for harness in started:
                try:
                    diagnostics = await asyncio.to_thread(harness.diagnostics)
                    logger.info(
                        "%s diagnostics before teardown:\n%s",
                        harness.name,
                        diagnostics,
                    )
                except Exception:
                    logger.exception("diagnostics of %s failed", harness.name)
        for harness in started:
            try:
                await asyncio.to_thread(harness.down)
            except Exception:
                logger.exception("teardown of %s failed", harness.name)
        # Reap every room each agent is in: driver-provisioned rooms and rooms
        # the agent created on its own (owner hubs). reap_room keeps the
        # ResourceManager's ledger consistent, so the later reap_all never
        # double-deletes. Must run while the agents still exist (the listing
        # is agent-authenticated).
        for pa in live.values():
            try:
                for room_id in await _agent_room_ids(pa.agent, settings):
                    await resources.reap_room(room_id)
            except Exception:
                logger.exception("room cleanup for %s failed", pa.agent.name)


@pytest.fixture
def pa(pa_name: str, pas: dict[str, PA]) -> PA:
    return pas[pa_name]


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
