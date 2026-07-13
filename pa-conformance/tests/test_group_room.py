"""L3 group-room scenario: multi-mention fan-out.

The fan-out scenario proves one multi-mention user turn is delivered to and
processed by every selected PA: each must post a responsive reply after the
group turn. The instruction asks for a token echo, giving compliant models a
deterministic answer, but the assertion is reply presence, not token
content — instruction compliance is LLM posture (live-observed: Hermes
sometimes declines token echoes), not platform conformance.

Multi-author attribution (a PA naming which peer authored an earlier turn) is
deliberately absent: Band scopes an agent's context to the messages addressed
to it (see test_history_visibility), so a reader can never see a peer's turn
and could only pass by guessing from the two-agent roster. Routed sender
identity for turns an agent DOES receive is covered by test_interagent.
"""

from __future__ import annotations

import pytest

from conftest import PA, RoomFactory, selected_harnesses
from driver.exchange import marker
from driver.ops import PAUserOps
from driver.sdk import CaptureFactory
from driver.waits import wait_for_replies_from


@pytest.mark.skipif(
    len(selected_harnesses()) < 2,
    reason="the group fan-out needs at least two harnesses",
)
async def test_group_mention_fans_out(
    pas: dict[str, PA],
    room_with: RoomFactory,
    user_ops: PAUserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    members = [pas[name] for name in selected_harnesses()]
    token = marker(run_id, prefix="PA-GROUP")

    room_id = await room_with(members, title="pa-group")

    async with capture(room_id) as room:
        group_turn = len(room.messages)
        await user_ops.send_mentioning_all(
            room_id,
            f"Introduce yourself in one short sentence that ends with {token}.",
            mentions=[m.agent for m in members],
        )
        replies = await wait_for_replies_from(
            room, [m.agent.id for m in members], since=group_turn
        )

    for member in members:
        replies[member.agent.id].assert_present(
            what=f"a reply to the group turn from {member.harness.name}"
        )
