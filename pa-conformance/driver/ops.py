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
    """Toolkit UserOps plus PA-suite structured-mention sends."""

    async def send_structured_mentions(
        self,
        room_id: str,
        content: str,
        *,
        mentions: Sequence[ProvisionedAgent],
    ) -> str:
        """Send ``content`` with delivery mentions, without rewriting its text.

        Band routes agent delivery from the structured ``mentions`` metadata.
        Keeping ``content`` untouched lets conformance scenarios distinguish
        platform routing from a harness's optional textual-address parsing.
        """
        response = await self._client.human_api_messages.send_my_chat_message(
            room_id,
            message=ChatMessageRequest(
                content=content,
                mentions=[
                    ChatMessageRequestMentionsItem(id=agent.id, name=agent.name)
                    for agent in mentions
                ],
            ),
        )
        return response.data.id

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
        return await self.send_structured_mentions(
            room_id,
            f"{prefix} {content}",
            mentions=mentions,
        )
