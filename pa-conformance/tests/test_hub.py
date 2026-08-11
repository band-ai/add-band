"""F1 owner-hub lifecycle.

Band does not expose a hub flag, so these rows observe its shared resulting
state: exactly one room containing only the owner and PA.  They deliberately
do not read runner-local hub state or assume a title.
"""

from __future__ import annotations

import pytest

from conftest import Owner
from driver.hub import owner_hub_room_ids
from driver.rooms import agent_room_ids
from driver.sdk import BaselineSettings
from harness.contract import PROFILE_FIELD

@pytest.mark.e2e
@pytest.mark.requires_profile(PROFILE_FIELD.provisions_hub)
async def test_owner_hub_is_unique(
    pa, owner: Owner, user_ops
) -> None:
    """A hub-provisioning harness exposes one private owner/PA control room."""
    hub_ids = await owner_hub_room_ids(
        user_ops=user_ops,
        agent=pa.agent,
        owner_id=owner.id,
        candidate_room_ids=pa.initial_room_ids,
    )

    assert len(hub_ids) == 1, (
        f"{pa.harness.name} has {len(hub_ids)} owner hubs; expected exactly one: "
        f"{sorted(hub_ids)}"
    )


@pytest.mark.e2e
@pytest.mark.requires_profile(PROFILE_FIELD.provisions_hub)
async def test_restart_preserves_the_unique_owner_hub(
    pa, owner: Owner, settings: BaselineSettings, user_ops
) -> None:
    """Restart reuses the provisioned owner hub rather than making another."""
    before = await agent_room_ids(pa.agent, settings)
    initial_hubs = await owner_hub_room_ids(
        user_ops=user_ops,
        agent=pa.agent,
        owner_id=owner.id,
        candidate_room_ids=pa.initial_room_ids,
    )
    assert len(initial_hubs) == 1, f"{pa.harness.name} has no unique initial hub"

    await pa.restart_and_wait_ready()

    after = await agent_room_ids(pa.agent, settings)
    assert after == before, (
        f"{pa.harness.name} changed its Band room set across restart: "
        f"before={sorted(before)}, after={sorted(after)}"
    )
