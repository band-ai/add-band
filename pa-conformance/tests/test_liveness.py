"""L0a liveness: each PA proves it processed a Band turn in a fresh room.

The run-scoped token distinguishes a response to this driver-created turn from
a generic acknowledgement or a stale reply. The prompt is framed as an owner
liveness check rather than "echo this exact string" — the latter reads as a
prompt-injection attempt and some harnesses (Hermes) refuse it. The test is
parametrized over the selected harnesses — never hand-listed.
"""

from __future__ import annotations

import pytest

from conftest import PA, RoomFactory, selected_harnesses
from driver.exchange import marker
from driver.sdk import CaptureFactory, UserOps
from driver.waits import wait_for_reply_from
from harness import HARNESS

pytestmark = pytest.mark.e2e


async def test_replies_to_direct_message(
    pa,
    room_with: RoomFactory,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
) -> None:
    token = marker(run_id, prefix="PA-L0")
    room_id = await room_with([pa], title=f"pa-liveness-{pa.harness.name}")

    async with capture(room_id) as room:
        await user_ops.send_message(
            room_id,
            f"Liveness check from your owner: reply with {token} to confirm "
            "you received this message.",
            mention_id=pa.agent.id,
            mention_name=pa.agent.name,
        )
        replies = await wait_for_reply_from(room, pa.agent.id, containing=token)

    replies.assert_contains_any([token])


@pytest.mark.parametrize("pa_name", ["hermes"])
@pytest.mark.known_gap(
    HARNESS.hermes,
    reason="INT-990: Hermes Band adapter drops cross-loop sends",
    intermittent=True,
)
@pytest.mark.skipif(
    "hermes" not in selected_harnesses(),
    reason="Hermes is not selected",
)
async def test_hermes_delivers_every_turn(
    pas: dict[str, PA],
    room_with: RoomFactory,
    user_ops: UserOps,
    capture: CaptureFactory,
    run_id: str,
    pa_name: str,
) -> None:
    """INT-990 regression guard: Hermes must deliver a reply on every turn.

    The Band adapter drops cross-loop sends (`asyncio Event is bound to a
    different event loop`), so a generated reply can fail to reach the room.
    Drive several back-to-back Hermes turns and require each to land — the
    delivery guarantee the bug breaks.
    """
    hermes = pas[pa_name]
    room_id = await room_with([hermes], title="pa-int990")

    async with capture(room_id) as room:
        for i in range(3):
            token = marker(run_id, prefix=f"PA-INT990-{i}")
            since = len(room.messages)
            await user_ops.send_message(
                room_id,
                f"Liveness check from your owner: reply with {token} to "
                "confirm you received this message.",
                mention_id=hermes.agent.id,
                mention_name=hermes.agent.name,
            )
            replies = await wait_for_reply_from(
                room, hermes.agent.id, since=since, containing=token
            )
            replies.assert_contains_any([token])
