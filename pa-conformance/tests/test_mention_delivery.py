"""L2 mention delivery: an unaddressed turn does not prompt a reply.

Room-history visibility is an agent policy. This test asserts only the shared
delivery behavior: an agent does not independently reply to a turn addressed
to another participant.
"""

from __future__ import annotations

import pytest

from conftest import OwnerChatFactory
from driver.exchange import marker
from driver.sdk import ResourceManager, UserOps
from driver.waits import said_by

pytestmark = pytest.mark.e2e


async def test_unaddressed_turn_does_not_prompt_reply(
    pa,
    owner_chat: OwnerChatFactory,
    resources: ResourceManager,
    user_ops: UserOps,
    run_id: str,
) -> None:
    decoy = await resources.provision_agent(f"visibility-decoy-{pa.harness.name}")
    ambient = marker(run_id, prefix="PA-AMBIENT")
    control = marker(run_id, prefix="PA-CONTROL")

    async with owner_chat(pa) as chat:
        await user_ops.add_participant(chat.room_id, decoy.id)
        await user_ops.send_message(
            chat.room_id,
            f"Note for you only: the marker is {ambient}. Reply with it.",
            mention_id=decoy.id,
            mention_name=decoy.name,
        )
        (await chat.ask(token=control)).assert_contains_any([control])
        unsolicited = said_by(
            chat.room, pa.agent.id, ambient, excluding=control
        )

    assert not unsolicited, (
        f"{pa.harness.name} replied to a turn addressed to another agent: "
        f"{[message.content for message in unsolicited]}"
    )
