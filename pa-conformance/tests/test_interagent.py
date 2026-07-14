"""L3 inter-agent exchange: in a shared room, one PA @mentions another with a
bounded ask-and-relay and a deterministic marker comes back within the
turn/timeout bound.

The asker/responder pair is the first two selected harnesses — the exchange
mechanics under test (structured mentions, targeted delivery, non-owner
prompts answered) are identical for any ordered pair; per-pair coverage is
later-phase scorecard work.
"""

from __future__ import annotations

import pytest

from conftest import PA, RoomFactory, selected_harnesses
from driver.exchange import marker, run_exchange
from driver.sdk import CaptureFactory, UserOps

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(
    len(selected_harnesses()) < 2,
    reason="the inter-agent exchange needs at least two harnesses",
)
async def test_seeded_ask_and_relay(
    pas: dict[str, PA],
    room_with: RoomFactory,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    asker, responder = (pas[name] for name in selected_harnesses()[:2])

    room_id = await room_with([asker, responder], title="pa-interagent")

    async with capture(room_id) as room:
        outcome = await run_exchange(
            capture=room,
            user_ops=user_ops,
            room_id=room_id,
            asker=asker.agent,
            asker_mention_name=asker.agent.name,
            responder=responder.agent,
            responder_handle=responder.handle,
            token=marker(run_id),
        )

    outcome.assert_completed()
    outcome.assert_bounded()
