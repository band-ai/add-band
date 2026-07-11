"""L0a liveness: each PA proves it processed a Band turn in a fresh room.

The run-scoped codeword distinguishes a response to this driver-created turn
from a generic acknowledgement or a stale reply. The test is parametrized over
the selected harnesses — never hand-listed.
"""

from __future__ import annotations

import asyncio

from driver.exchange import codeword
from driver.sdk import CaptureFactory, ResourceManager, UserOps
from driver.waits import wait_for_reply_from


async def test_replies_to_direct_message(
    pa,
    resources: ResourceManager,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    token = codeword(run_id, prefix="PA-L0")
    room_id = await resources.provision_room(
        title=f"pa-liveness-{pa.harness.name}", participants=[pa.agent.id]
    )
    await asyncio.to_thread(pa.harness.attach_room, room_id)

    async with capture(room_id) as room:
        await user_ops.send_message(
            room_id,
            f"Reply with the exact codeword {token} and nothing else.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        replies = await wait_for_reply_from(room, pa.agent.id, containing=token)

    replies.assert_contains_any([token])
