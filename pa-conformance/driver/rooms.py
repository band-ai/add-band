"""Agent-authenticated room discovery for PA conformance scenarios."""

from __future__ import annotations

from driver.sdk import BaselineSettings, ProvisionedAgent, agent_rest_client


async def agent_room_ids(
    agent: ProvisionedAgent, settings: BaselineSettings
) -> frozenset[str]:
    """Return the set of rooms the agent currently participates in.

    Participation is an unordered set: the agent-chat listing carries no
    guaranteed order and can reshuffle across a restart, so the return type is
    a frozenset — callers compare room identity, never sequence.

    This read uses the agent's own credentials: owner-scoped room listings do
    not include harness-created owner hubs consistently across harnesses.
    """
    response = await agent_rest_client(agent, settings).agent_api_chats.list_agent_chats()
    return frozenset(room.id for room in response.data or [])
