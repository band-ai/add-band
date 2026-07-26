"""T1 context composition: what the harness actually feeds its model.

Every assertion reads the recorded ModelCall — the turn's composed context
exactly as the harness put it on the provider wire (the Tier-1 read point;
INT-800's observation seam, PA translation). The turn runs live through the
stand-in's passthrough; the wire is read afterwards.

All rows gate on the Profile's model_wire verdict (a harness whose model calls
can't be routed skips — the INT-986 N-A rule); PA_STANDIN=off skips too.
"""

from __future__ import annotations

import pytest

from conftest import Owner, OwnerChatFactory
from driver.exchange import marker
from harness.contract import PROFILE_FIELD

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_profile(PROFILE_FIELD.model_wire),
]


async def test_turn_and_author_render_into_context(
    pa, owner_chat: OwnerChatFactory, owner: Owner, run_id: str
) -> None:
    """L0a: the delivered turn and its author render into the per-turn model
    context — the turn arrives attributed to the sending user, not anonymous.
    Attribution format is harness-specific (Hermes prefixes the display name,
    NanoClaw a sender=<id> entry, OpenClaw both), so the bar is that the author
    is identifiable by name or id."""
    token = marker(run_id, prefix="PA-T1-CTX")

    async with owner_chat(pa) as chat:
        call = await chat.ask_scripted(token=token)

    assert call.attributes_to(owner), (
        f"{pa.harness.name} composed the turn without an attributable author: "
        f"neither {owner.name!r} nor {owner.id!r} in the context carrying {token}"
    )


async def test_same_room_turns_share_thread(
    pa, owner_chat: OwnerChatFactory, run_id: str
) -> None:
    """L2 thread identity: two turns in one Band room land in one model
    thread — turn 2's context carries turn 1's marker. The marker is
    room-specific, so this proves the room's own transcript recovered into the
    thread, not merely that some history rendered."""
    first = marker(run_id, prefix="PA-T1-THREAD1")
    second = marker(run_id, prefix="PA-T1-THREAD2")

    async with owner_chat(pa) as chat:
        await chat.ask_scripted(token=first)
        call = await chat.ask_scripted(token=second)

    assert call.carries(first), (
        f"{pa.harness.name} composed turn 2 without turn 1's content — "
        f"same-room turns are not sharing a thread ({first} absent)"
    )
