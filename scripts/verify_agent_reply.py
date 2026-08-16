#!/usr/bin/env python3
"""Verify a Band agent actually replies — the onboarding success gate.

An agent that logs "Agent started" has only connected its WebSocket; it can
still be unable to answer a single message (e.g. the Claude Code subprocess
has no working credentials). This script is the real check: it creates a
throwaway room, sends the agent a uniquely-tokened @mention, and only reports
success once a reply carrying the token comes back.

Runs inside the scaffolded project's venv (``uv run python <this file>``) —
it needs the ``band-sdk`` package, which every scaffold already depends on.

Environment:
  BAND_USER_API_KEY       Band user API key (required; never written to disk)
  VERIFY_AGENT_ID         id of the agent to check (required)
  VERIFY_AGENT_NAME       display name of the agent to check (required)
  BAND_REST_URL           platform base URL (default https://app.band.ai)
  VERIFY_TIMEOUT_SECONDS  how long to wait for the reply (default 60)

Exit code 0: the agent replied. Anything else: it did not — do not tell the
user their setup works.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import httpx
from band.client.rest import (
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    RestClient,
)
from band_rest import ParticipantRequest
from band_rest.human_api_chats import CreateMyChatRoomRequestChat
from dotenv import load_dotenv

# Picks up BAND_REST_URL from the scaffold's .env; real environment variables
# (the key, the agent id/name) are never overridden.
load_dotenv()

POLL_INTERVAL_SECONDS = 2.0


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"verify: {name} must be set", file=sys.stderr)
        raise SystemExit(2)
    return value


def _delete_room(client: RestClient, room_id: str) -> None:
    """Best-effort cleanup; the Fern client has no delete-chat method yet."""
    wrapper = client._client_wrapper
    url = f"{wrapper.get_base_url().rstrip('/')}/api/v1/me/chats/{room_id}"
    try:
        httpx.delete(url, headers=wrapper.get_headers(), timeout=30.0)
    except httpx.HTTPError:
        pass


def main() -> int:
    api_key = _require_env("BAND_USER_API_KEY")
    agent_id = _require_env("VERIFY_AGENT_ID")
    agent_name = _require_env("VERIFY_AGENT_NAME")
    base_url = os.environ.get("BAND_REST_URL", "https://app.band.ai").rstrip("/")
    timeout = float(os.environ.get("VERIFY_TIMEOUT_SECONDS", "60"))

    token = uuid.uuid4().hex[:12]
    client = RestClient(api_key=api_key, base_url=base_url)

    room = client.human_api_chats.create_my_chat_room(
        chat=CreateMyChatRoomRequestChat(title="Band onboarding check")
    )
    room_id = room.data.id
    try:
        client.human_api_participants.add_my_chat_participant(
            room_id, participant=ParticipantRequest(participant_id=agent_id)
        )
        client.human_api_messages.send_my_chat_message(
            room_id,
            message=ChatMessageRequest(
                content=(
                    f"@{agent_name} connectivity check — please reply and "
                    f"include the token {token} in your reply."
                ),
                mentions=[
                    ChatMessageRequestMentionsItem(id=agent_id, name=agent_name)
                ],
            ),
        )

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_SECONDS)
            messages = client.human_api_messages.list_my_chat_messages(
                room_id, limit=50
            ).data
            for message in messages:
                if message.sender_id != agent_id:
                    continue
                if message.message_type == "error":
                    print(
                        f"verify: {agent_name} reported an error instead of "
                        f"replying:\n  {message.content}",
                        file=sys.stderr,
                    )
                    return 1
                if message.message_type == "text" and token in message.content:
                    print(f"verify: {agent_name} replied: {message.content}")
                    return 0

        print(
            f"verify: {agent_name} did not reply within {timeout:.0f}s. "
            "The agent process is connected but cannot answer messages. "
            "Most likely its LLM credentials are broken — for the Claude "
            "Agent SDK, check `claude login` / ANTHROPIC_API_KEY, and check "
            "for a stray ANTHROPIC_API_KEY in your shell environment that "
            "silently overrides a valid `claude login`.",
            file=sys.stderr,
        )
        return 1
    finally:
        _delete_room(client, room_id)


if __name__ == "__main__":
    raise SystemExit(main())
