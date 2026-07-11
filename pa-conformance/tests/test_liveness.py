"""Phase-0 liveness: each PA, in a driver-created room, answers a direct
@mention (INT-987 deliverable #3). Parametrized over the selected harnesses —
never hand-listed."""

from __future__ import annotations

import asyncio

from driver.sdk import CaptureFactory, ResourceManager, UserOps
from driver.waits import wait_for_reply_from


async def test_replies_to_direct_message(
    pa,
    resources: ResourceManager,
    user_ops: UserOps,
    capture: CaptureFactory,
) -> None:
    room_id = await resources.provision_room(
        title=f"pa-liveness-{pa.harness.name}", participants=[pa.agent.id]
    )
    await asyncio.to_thread(pa.harness.attach_room, room_id)

    async with capture(room_id) as room:
        await user_ops.send_message(
            room_id,
            "Reply with a short greeting.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        replies = await wait_for_reply_from(room, pa.agent.id)

    replies.assert_present(what=f"a reply from {pa.harness.name}")
