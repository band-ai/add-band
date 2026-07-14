"""L2 mention delivery: an unaddressed turn does not prompt a reply.

Room-history visibility is an agent policy. This test asserts only the shared
delivery behavior: an agent does not independently reply to a turn addressed
to another participant.
"""

from __future__ import annotations

import pytest
from faker import Faker

from conftest import OwnerChatFactory
from driver.exchange import marker
from driver.sdk import ResourceManager, UserOps
from driver.waits import said_by

pytestmark = pytest.mark.e2e


def _liveness_name(run_id: str) -> str:
    """A natural, run-scoped person name for the liveness probe.

    Faker-generated and seeded by the run id so it is deterministic per run yet
    reads as an ordinary name. A bare token like ``PA-CONTROL-<run>`` trips
    Hermes's prompt-injection guard, which refuses to echo control-code-shaped
    strings; a name woven into a joke is answered normally.
    """
    faker = Faker()
    faker.seed_instance(run_id)
    return faker.name()


async def test_unaddressed_turn_does_not_prompt_reply(
    pa,
    owner_chat: OwnerChatFactory,
    resources: ResourceManager,
    user_ops: UserOps,
    run_id: str,
) -> None:
    decoy = await resources.provision_agent(f"visibility-decoy-{pa.harness.name}")
    ambient = marker(run_id, prefix="PA-AMBIENT")
    control = _liveness_name(run_id)

    async with owner_chat(pa) as chat:
        await user_ops.add_participant(chat.room_id, decoy.id)
        await user_ops.send_message(
            chat.room_id,
            f"Note for you only: the marker is {ambient}. Reply with it.",
            mention_id=decoy.id,
            mention_name=decoy.name,
        )
        # Frame the liveness probe as a creative task naming an ordinary person
        # rather than "reply with this token": Hermes's prompt-injection guard
        # refuses to echo a control-code-shaped token, which fails the probe on
        # a live model.
        liveness = (
            f'Tell me a short, light-hearted one-line joke about someone named '
            f'"{control}", and use that exact name in the joke.'
        )
        (await chat.ask(token=control, prompt=liveness)).assert_contains_any([control])
        unsolicited = said_by(
            chat.room, pa.agent.id, ambient, excluding=control
        )

    assert not unsolicited, (
        f"{pa.harness.name} replied to a turn addressed to another agent: "
        f"{[message.content for message in unsolicited]}"
    )
