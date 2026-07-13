"""L2 conversational state: same-room recall and cross-room isolation.

The recall answer combines the earlier fact with a random suffix disclosed only
in turn two. A late reply from turn one therefore cannot satisfy the assertion.
The isolation scenario gives a fact only to room A and requires room B to return
a room-B-only fallback. Both tests are parametrized over the selected harnesses.
"""

from __future__ import annotations

from secrets import token_hex

import pytest

from conftest import RoomFactory
from driver.exchange import marker
from driver.sdk import CaptureFactory, UserOps
from driver.waits import wait_for_reply_from


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


# A live cross-room leak is rare but non-deterministic (measured ~0/15), and the
# room-A confirmation can also be dropped in flight. Retry only that seeding
# exchange; the room-B isolation assertion runs once against the seeded fact.
# Two Hermes leak vectors are already closed in harness config; a third
# (session-history search) is a ticketed upstream gap — see the known_gap
# contract in conftest for the XFAIL/XPASS semantics.
@pytest.mark.known_gap(
    "hermes",
    reason="INT-991: hermes leaks cross-room via session history",
    intermittent=True,
)
async def test_does_not_leak_fact_between_rooms(
    pa,
    room_with: RoomFactory,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    fact = marker(run_id, prefix="PA-ROOM-A")
    unknown_marker = f"UNKNOWN-{token_hex(8).upper()}"
    room_a = await room_with([pa], title=f"pa-isolation-a-{pa.harness.name}")
    room_b = await room_with([pa], title=f"pa-isolation-b-{pa.harness.name}")

    # Seed the fact in room A. A concrete "reply with STORED" reliably elicits a
    # reply (a vague "confirm" sometimes gets none); the exact wording doesn't
    # matter — this step only needs the turn processed, so assert a reply
    # happened, not a verbatim marker.
    async with capture(room_a) as room:
        stored = None
        for _ in range(3):
            since = len(room.messages)
            await user_ops.send_message(
                room_a,
                f"Remember this room's marker: {fact}. Reply with STORED once you have it.",
                mention_id=pa.agent.id,
                mention_name=pa.agent.name,
            )
            stored = await wait_for_reply_from(
                room, pa.agent.id, since=since, containing="STORED"
            )
            if stored:
                break
    assert stored is not None
    stored.assert_present(what=f"a room-A store confirmation from {pa.harness.name}")

    # unknown_marker still anchors the wait on the model's final answer (so a
    # leak in a later message isn't missed), but the assertion is the real
    # conformance — room A's fact must not surface in room B — not whether the
    # model echoed the marker verbatim.
    async with capture(room_b) as room:
        await user_ops.send_message(
            room_b,
            "Reply with the marker previously given in this room. If no "
            f"marker was given in this room, reply with {unknown_marker}.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        isolated = await wait_for_reply_from(
            room, pa.agent.id, containing=unknown_marker
        )

    isolated.assert_present(what=f"a room-B reply from {pa.harness.name}")
    assert all(
        fact.lower() not in (message.content or "").lower() for message in isolated
    ), f"{pa.harness.name} leaked room A's marker into room B"
