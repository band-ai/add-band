"""L3 group-room scenarios: fan-out and attributed multi-author history.

The fan-out scenario requires every selected PA to echo one run-scoped token,
which proves each one processed the same delivered group turn rather than
merely emitting an interim reply.
"""

from __future__ import annotations

import asyncio

import pytest

from conftest import PA, selected_harnesses
from driver.exchange import codeword
from driver.ops import PAUserOps
from driver.sdk import CaptureFactory, ResourceManager
from driver.waits import wait_for_replies_from, wait_for_reply_from


async def test_group_mention_fans_out(
    pas: dict[str, PA],
    resources: ResourceManager,
    user_ops: PAUserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    if len(selected_harnesses()) < 2:
        pytest.skip("the group fan-out needs at least two harnesses")
    members = [pas[name] for name in selected_harnesses()]
    token = codeword(run_id, prefix="PA-GROUP")

    room_id = await resources.provision_room(
        title="pa-group", participants=[m.agent.id for m in members]
    )
    for member in members:
        await asyncio.to_thread(member.harness.attach_room, room_id)

    async with capture(room_id) as room:
        await user_ops.send_mentioning_all(
            room_id,
            f"Introduce yourself in one short sentence that ends with {token}.",
            mentions=[m.agent for m in members],
        )
        replies = await wait_for_replies_from(
            room, [m.agent.id for m in members], containing=token
        )

    for member in members:
        replies[member.agent.id].assert_present(
            what=f"an intro containing {token} from {member.harness.name}"
        )


async def test_multi_author_history_preserves_sender_identity(
    pas: dict[str, PA],
    resources: ResourceManager,
    user_ops: PAUserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    """A second PA identifies which first PA authored an earlier room turn.

    The driver tells neither PA the expected author in the reader's turn. A
    matching display name therefore requires rostered, attributed history
    rather than treating another PA's text as the reader's own prior turn.
    """
    if len(selected_harnesses()) < 2:
        pytest.skip("attributed multi-author history needs at least two harnesses")
    author, reader = (pas[name] for name in selected_harnesses()[:2])
    token = codeword(run_id, prefix="PA-AUTHOR")

    room_id = await resources.provision_room(
        title="pa-attribution",
        participants=[author.agent.id, reader.agent.id],
    )
    for member in (author, reader):
        await asyncio.to_thread(member.harness.attach_room, room_id)

    async with capture(room_id) as room:
        await user_ops.send_message(
            room_id,
            f"Reply with the exact codeword {token} and nothing else.",
            mention_id=author.agent.id,
            mention_name=author.agent.name,
        )
        await wait_for_reply_from(room, author.agent.id, containing=token)

        reader_turn = len(room.messages)
        await user_ops.send_message(
            room_id,
            f"Which agent authored the earlier message containing {token}? "
            "Reply with that agent's display name and nothing else.",
            mention_id=reader.agent.id,
            mention_name=reader.agent.name,
        )
        attribution = await wait_for_reply_from(
            room,
            reader.agent.id,
            since=reader_turn,
            containing=author.agent.name,
        )

    attribution.assert_contains_any([author.agent.name])
