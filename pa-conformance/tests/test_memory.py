"""L2 conversational state: same-room recall and cross-room isolation.

The recall answer combines the earlier fact with a random suffix disclosed only
in turn two. A late reply from turn one therefore cannot satisfy the assertion.
The isolation scenario gives a fact only to room A and requires room B to return
a room-B-only fallback. Both tests are parametrized over the selected harnesses.
"""

from __future__ import annotations

import asyncio
from secrets import token_hex

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
    suffix = token_hex(12).upper()
    recall_token = f"{fact}-{suffix}"
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
            "Take the codeword I gave you earlier, append a hyphen and this "
            f"new suffix: {suffix}. Reply with the resulting combined codeword "
            "and nothing else.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        recall = await wait_for_reply_from(
            room, pa.agent.id, since=turn_two, containing=recall_token
        )

    recall.assert_contains_any([recall_token])


async def test_does_not_leak_fact_between_rooms(
    pa,
    resources: ResourceManager,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    fact = codeword(run_id, prefix="PA-ROOM-A")
    stored_marker = f"STORED-{token_hex(8).upper()}"
    unknown_marker = f"UNKNOWN-{token_hex(8).upper()}"
    room_a = await resources.provision_room(
        title=f"pa-isolation-a-{pa.harness.name}", participants=[pa.agent.id]
    )
    room_b = await resources.provision_room(
        title=f"pa-isolation-b-{pa.harness.name}", participants=[pa.agent.id]
    )
    for room_id in (room_a, room_b):
        await asyncio.to_thread(pa.harness.attach_room, room_id)

    async with capture(room_a) as room:
        await user_ops.send_message(
            room_a,
            f"Remember this room's codeword: {fact}. Reply with {stored_marker}.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        stored = await wait_for_reply_from(
            room, pa.agent.id, containing=stored_marker
        )
    stored.assert_contains_any([stored_marker])

    async with capture(room_b) as room:
        await user_ops.send_message(
            room_b,
            "Reply with the codeword previously given in this room. If no "
            f"codeword was given in this room, reply with {unknown_marker}.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        isolated = await wait_for_reply_from(
            room, pa.agent.id, containing=unknown_marker
        )

    isolated.assert_contains_any([unknown_marker])
    assert all(
        fact.lower() not in (message.content or "").lower()
        for message in isolated
    )
