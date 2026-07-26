"""L2 conversational state: same-room recall.

The recall answer combines the earlier fact with a random suffix disclosed only
in turn two. A late reply from turn one therefore cannot satisfy the assertion.
The test is parametrized over the selected harnesses.
"""

from __future__ import annotations

from secrets import token_hex

import pytest

from driver.exchange import marker
from driver.sdk import CaptureFactory, UserOps
from driver.waits import wait_for_reply_from
from harness import HARNESS

pytestmark = pytest.mark.e2e


async def test_recalls_fact_from_earlier_turn(
    pa,
    room_with: RoomFactory,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    fact = marker(run_id, prefix="PA-FACT")
    suffix = token_hex(12).upper()
    recall_token = f"{fact}-{suffix}"
    stored = "STORED-OK"
    room_id = await room_with([pa], title=f"pa-memory-{pa.harness.name}")

    async with capture(room_id) as room:
        await user_ops.send_message(
            room_id,
            f"Remember this marker: {fact}. Reply with only the word "
            f"{stored} once you have it.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        stored_reply = await wait_for_reply_from(
            room, pa.agent.id, containing=stored
        )
        stored_reply.assert_present(
            what=f"a room-A store confirmation from {pa.harness.name}"
        )

        turn_two = len(room.messages)
        await user_ops.send_message(
            room_id,
            "Take the marker I gave you earlier, append a hyphen and this "
            f"new suffix: {suffix}. Reply with the resulting combined marker "
            "and nothing else.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        recall = await wait_for_reply_from(
            room, pa.agent.id, since=turn_two, containing=recall_token
        )

    recall.assert_contains_any([recall_token])
