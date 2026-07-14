"""F4 — onboarding via the published catalog path.

The conformance bar (todo.md, "F4 — Onboarding & publishing"): following the
catalog's own bootstrap from a clean install reaches an agent that serves on
Band. The bootstrap mints its own agent from the user key — nothing is
pre-provisioned — and it runs VERBATIM, so what breaks for users breaks here
first (including unpinned pieces the guide ships, like OpenClaw's `@latest`
channel plugin). The minted agent's live reply is the "connected" proof;
OpenClaw's published path provisions no hub.

Hermes's and NanoClaw's published paths END in an interactive AI session
(`hermes chat -s band:add-band`, `claude /add-band` — the session owns the
real install), so their rows are declared skips until a scripted skill-runner
exists to drive those sessions headlessly.
"""

from __future__ import annotations

import pytest

from conftest import BootstrapOnboard
from driver.chat import OwnerChat
from driver.exchange import liveness_name
from driver.sdk import CaptureFactory, ResourceManager, UserOps

pytestmark = pytest.mark.e2e


@pytest.mark.harness_skip(
    "hermes",
    reason="the published path hands off to an interactive AI session "
    "(hermes chat -s band:add-band); needs a scripted skill-runner",
)
@pytest.mark.harness_skip(
    "nanoclaw",
    reason="the published path hands off to an interactive AI session "
    "(claude /add-band); needs a scripted skill-runner",
)
async def test_published_bootstrap_onboards_a_responding_agent(
    pa_name: str,
    bootstrap_onboard: BootstrapOnboard,
    resources: ResourceManager,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    agent = await bootstrap_onboard(pa_name)
    token = liveness_name(run_id)
    room_id = await resources.provision_room(
        title=f"pa-onboard-{pa_name}", participants=[agent.id]
    )

    # A bootstrap-minted agent, not a session `pa`, so OwnerChat is built
    # directly on the provisioned room rather than via the owner_chat fixture.
    async with capture(room_id) as room:
        chat = OwnerChat(agent=agent, room=room, user_ops=user_ops, standin=None)
        reply = await chat.ask(token=token)

    reply.assert_contains_any([token])
