"""Hermetic coverage for agent-authenticated room discovery."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from driver.rooms import agent_room_ids
from driver.sdk import ProvisionedAgent


@pytest.mark.hermetic
async def test_agent_room_ids_uses_the_agent_scoped_chat_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed_rooms = [SimpleNamespace(id="scenario-room"), SimpleNamespace(id="hub-room")]
    client = SimpleNamespace(
        agent_api_chats=SimpleNamespace(
            list_agent_chats=AsyncMock(return_value=SimpleNamespace(data=listed_rooms))
        )
    )
    agent = ProvisionedAgent(id="agent-id", api_key="agent-key", name="agent-name")
    settings = object()

    monkeypatch.setattr("driver.rooms.agent_rest_client", lambda actual, _: client)

    assert await agent_room_ids(agent, settings) == frozenset({"hub-room", "scenario-room"})
    client.agent_api_chats.list_agent_chats.assert_awaited_once_with()
