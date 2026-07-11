"""Group fan-out: one user message mentions every selected PA in one Band room.
Each harness answers in the same room. A run-scoped token in the prompt, echoed
back per harness, is what proves each one processed the message — not the bare
presence of a reply (an interim/non-answer notice would satisfy that)."""

from __future__ import annotations

import asyncio

import pytest

from conftest import PA, selected_harnesses
from driver.exchange import codeword
from driver.ops import PAUserOps
from driver.sdk import CaptureFactory, ResourceManager
from driver.waits import wait_for_replies_from


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
