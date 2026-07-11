"""The driver's send surface.

The toolkit's ``UserOps`` mentions one agent per message. The group tests
exercise the platform's multi-mention fan-out, which it doesn't cover, so
``PAUserOps`` extends it with ``send_mentioning_all`` — keeping every
driver-side send in a test behind one object (the ``user_ops`` fixture),
rather than reaching past it to the raw REST client.
"""

from __future__ import annotations

from collections.abc import Sequence

from band_rest import ChatMessageRequest, ChatMessageRequestMentionsItem

from driver.sdk import ProvisionedAgent, UserOps


class PAUserOps(UserOps):
    """Toolkit UserOps plus the suite's own multi-mention send."""

    async def send_mentioning_all(
        self,
        room_id: str,
        content: str,
        *,
        mentions: Sequence[ProvisionedAgent],
    ) -> str:
        """Send one user message @mentioning every agent in ``mentions``;
        return the message id. Band delivers the message to each mentioned
        agent. Mirrors UserOps.send_message's convention (``@Name`` text
        prefixes matching the structured mentions)."""
        prefix = " ".join(f"@{agent.name}" for agent in mentions)
        response = await self._client.human_api_messages.send_my_chat_message(
            room_id,
            message=ChatMessageRequest(
                content=f"{prefix} {content}",
                mentions=[
                    ChatMessageRequestMentionsItem(id=agent.id, name=agent.name)
                    for agent in mentions
                ],
            ),
        )
        return response.data.id
