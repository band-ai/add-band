"""Phase-0 inter-agent exchange (INT-987 deliverable #4): in a shared room,
one PA @mentions another with a bounded ask-and-relay and a deterministic
codeword comes back within the turn/timeout bound.

The asker/responder pair is the first two selected harnesses — the exchange
mechanics under test (structured mentions, targeted delivery, non-owner
prompts answered) are identical for any ordered pair; per-pair coverage is
later-phase scorecard work, not Phase 0.
"""

from __future__ import annotations

import asyncio

import pytest

from conftest import PA, selected_harnesses
from driver.exchange import codeword, run_exchange
from driver.sdk import CaptureFactory, ResourceManager, UserOps


async def test_seeded_ask_and_relay(
    pas: dict[str, PA],
    resources: ResourceManager,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    if len(selected_harnesses()) < 2:
        pytest.skip("the inter-agent exchange needs at least two harnesses")
    asker, responder = (pas[name] for name in selected_harnesses()[:2])

    room_id = await resources.provision_room(
        title="pa-interagent",
        participants=[asker.agent.id, responder.agent.id],
    )
    for pa in (asker, responder):
        await asyncio.to_thread(pa.harness.attach_room, room_id)

    async with capture(room_id) as room:
        outcome = await run_exchange(
            capture=room,
            user_ops=user_ops,
            room_id=room_id,
            asker=asker.agent,
            asker_mention_name=asker.agent.name,
            responder=responder.agent,
            responder_handle=responder.handle,
            token=codeword(run_id),
        )

    outcome.assert_completed()
    outcome.assert_bounded()
