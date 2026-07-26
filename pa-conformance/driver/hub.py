"""Band-side discovery of a PA's private owner hub.

The platform does not label a room as a hub.  The shared observable shape is
therefore a room the PA participates in whose active participants are exactly
the PA and its owner.  Harness-local persistence details stay in each
runner's Profile and are deliberately not inspected here.
"""

from __future__ import annotations

from collections.abc import Iterable

from driver.sdk import ProvisionedAgent, UserOps


async def owner_hub_room_ids(
    *,
    user_ops: UserOps,
    agent: ProvisionedAgent,
    owner_id: str,
    candidate_room_ids: Iterable[str],
) -> set[str]:
    """Return candidate rooms containing exactly the owner and that agent."""
    expected_participants = {owner_id, agent.id}
    hub_ids: set[str] = set()

    for room_id in candidate_room_ids:
        participant_ids = set(await user_ops.list_participant_ids(room_id))
        if participant_ids == expected_participants:
            hub_ids.add(room_id)

    return hub_ids
