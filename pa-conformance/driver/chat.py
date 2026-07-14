"""The owner's side of a conversation with one PA in one room.

`OwnerChat` binds the wiring a turn needs — the agent, the room capture, the
owner send surface, and (when enabled) the model stand-in — so a scenario reads
as intent: `await chat.ask(token=…)`, `await chat.ask_scripted(token=…)`. It
tracks the reply-buffer and wire cursors internally, so tests never index the
buffer or snapshot a cursor by hand.

Scripting is correlated by the run-scoped token in the turn's latest user
message, so a scripted turn need not be the room's first — but the `owner_chat`
fixture opens a fresh room, which keeps the common case (a single scripted
turn) free of interleaving model traffic.
"""

from __future__ import annotations

import pytest

from driver.sdk import ProvisionedAgent, Replies, ReplyCapture, UserOps
from driver.standin import Decision, ModelCall, ModelStandIn, Tool, call, decision
from driver.waits import wait_for_reply_from

#: Echoes queued per scripted turn: identical replies absorbing a harness's
#: retries / multi-inference turns (Hermes consumes two when its format parser
#: retries).
_SCRIPT_DEPTH = 3


class OwnerChat:
    """A live conversation the owner drives with one PA. One per room."""

    def __init__(
        self,
        *,
        agent: ProvisionedAgent,
        room: ReplyCapture,
        user_ops: UserOps,
        standin: ModelStandIn | None,
    ) -> None:
        self._agent = agent
        self._room = room
        self._user_ops = user_ops
        self._standin = standin
        self._replies_seen = 0  # reply-buffer high-water mark, per turn
        self._wire_from = 0  # model cursor captured at the last turn's send

    @property
    def room_id(self) -> str:
        return self._room.room_id

    @property
    def room(self) -> ReplyCapture:
        """The live reply capture — for observations the verbs don't cover
        (delivery status, absence checks over the buffer)."""
        return self._room

    @property
    def settled(self) -> int:
        """The reply-buffer position after the last settled turn — a mark to
        scope a later absence check (`said_by(chat.room, …, since=mark)`) to
        what happened after this point."""
        return self._replies_seen

    async def ask(self, *, token: str, prompt: str | None = None) -> Replies:
        """Send one owner @mention turn and wait for the PA's reply carrying
        `token`; return the reply window. Works with or without the stand-in."""
        if self._standin is not None:
            self._wire_from = await self._standin.cursor()
        await self._send(token, prompt)
        replies = await wait_for_reply_from(
            self._room, self._agent.id, since=self._replies_seen, containing=token
        )
        self._replies_seen = len(self._room.messages)
        return replies

    async def send(self, *, prompt: str) -> str:
        """Send an owner @mention turn to the PA without waiting for a reply —
        for a turn delivered while the PA is down. Returns the Band message id."""
        return await self._send_prompt(prompt)

    async def ask_scripted(
        self, *, token: str, reply: str | None = None
    ) -> ModelCall:
        """Script the model's reply, drive the turn, and return the scripted
        agent-loop ModelCall — the composed context + tool surface the harness
        put on the wire."""
        model = self._require_standin()
        await model.script(token, *self._echoes(token, reply))
        await self.ask(token=token)
        try:
            return await model.await_call(
                carrying=token, since=self._wire_from, served="scripted"
            )
        finally:
            # The turn has settled; drop any echo padding it didn't consume so
            # it can't serve a later turn that happens to quote this token.
            await model.unscript(token)

    async def recorded_call(
        self,
        *,
        carrying: str,
        agent_loop: bool = False,
        tool_result: bool = False,
    ) -> ModelCall:
        """The recorded model request for the turn just driven (scoped to that
        turn), carrying `carrying`. `agent_loop` selects the tool-bearing
        request over a tool-less utility call that echoes the same token."""
        return await self._require_standin().await_call(
            carrying=carrying,
            since=self._wire_from,
            agent_loop=agent_loop,
            tool_result=tool_result,
        )

    async def dispatch(
        self, tool: Tool, *, room: str, token: str, follow_up: Decision | None = None
    ) -> ModelCall:
        """Script a tool call, drive the real loop, and return its tool result.

        A follow-up text decision keeps the complete loop deterministic. The
        optional terminal form is retained for live-model E2E callers that
        intentionally want the post-tool request to reach the provider.

        The follow-up is correlated by `token` (it still carries the prompt
        that opened the turn) as well as the tool_result — so unrelated tool
        traffic in the same session can't satisfy the wait, and the echoed tool
        id (which harnesses rewrite) is never relied on."""
        model = self._require_standin()
        self._wire_from = await model.cursor()
        decisions = [decision(tool_calls=[call(tool.name, tool.room_arg(room))])]
        if follow_up is None:
            await model.script(token, *decisions, terminal=True)
        else:
            await model.script(token, *decisions, follow_up)
        try:
            await self._send(token, None)
            return await model.await_call(
                carrying=token, since=self._wire_from, tool_result=True
            )
        finally:
            # A harness can abort its tool loop after the tool-result request.
            # Remove any unconsumed follow-up before a later turn can match it.
            await model.unscript(token)

    def _echoes(self, token: str, reply: str | None) -> tuple[Decision, ...]:
        return (decision(text=reply or f"Echo {token} confirmed."),) * _SCRIPT_DEPTH

    async def _send(self, token: str, prompt: str | None) -> str:
        return await self._send_prompt(
            prompt
            or f"Owner check: reply with {token} to confirm you received this message."
        )

    async def _send_prompt(self, text: str) -> str:
        return await self._user_ops.send_message(
            self._room.room_id,
            text,
            mention_id=self._agent.id,
            mention_name=self._agent.name,
        )

    def _require_standin(self) -> ModelStandIn:
        if self._standin is None:
            pytest.skip("stand-in disabled (PA_STANDIN=off)")
        return self._standin
