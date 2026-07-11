"""Conversational state: a PA recalls a fact from an earlier turn in the same
room. The reply to turn two is only correct if turn one is still in the
harness's context — a preview of the conformance ladder's read-state rungs.
Parametrized over the selected harnesses."""

from __future__ import annotations

import asyncio

from driver.exchange import codeword
from driver.sdk import CaptureFactory, ResourceManager, UserOps
from driver.waits import wait_for_reply_from


async def test_recalls_fact_from_earlier_turn(
    pa,
    resources: ResourceManager,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    fact = codeword(run_id, prefix="PA-FACT")
    # Turn 1 closes with a marker distinct from the fact: waiting on it drains
    # turn 1 to completion, so the turn-2 window starts strictly after turn 1
    # (including any interim notice AND any codeword echo in the ack). Matching
    # turn 2 on the fact can then only see a genuine recall, never turn 1's echo.
    stored = "STORED-OK"
    room_id = await resources.provision_room(
        title=f"pa-memory-{pa.harness.name}", participants=[pa.agent.id]
    )
    await asyncio.to_thread(pa.harness.attach_room, room_id)

    async with capture(room_id) as room:
        await user_ops.send_message(
            room_id,
            f"Remember this codeword: {fact}. Reply with only the word "
            f"{stored} once you have it.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        await wait_for_reply_from(room, pa.agent.id, containing=stored)

        turn_two = len(room.messages)
        await user_ops.send_message(
            room_id,
            "Reply with the exact codeword I gave you earlier, nothing else.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        recall = await wait_for_reply_from(
            room, pa.agent.id, since=turn_two, containing=fact
        )

    recall.assert_contains_any([fact])
