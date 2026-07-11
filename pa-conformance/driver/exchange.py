"""The bounded inter-agent exchanges: the pair ask-and-relay and the
three-way relay.

Both share one proof mechanism (from the INT-987 working doc): the driver
seeds one message in a shared room, @mentioning only the first agent. Band
only delivers messages to mentioned agents, so the seed — and the codeword
inside it — is invisible to everyone else; the codeword appearing in a later
agent's message proves the @mention chain carried it there. The pair exchange
proves one hop (asker → responder and back); the relay proves two
(first → via → source and back), with every leg required so a shortcut
straight to the source fails the middle leg.

Bounds, whichever hits first (the wait stops immediately on success):
  - a wall-clock deadline (~90s pair / ~150s relay)
  - a turn cap (6 / 10 agent messages, never open-ended) — enforced inside
    the wait predicate, so a chatty runaway fails fast instead of timing out.

The codeword embeds the run id, so a stale message from any earlier run can
never satisfy the predicate.
"""

from __future__ import annotations

from dataclasses import dataclass

from driver.sdk import ProvisionedAgent, Replies, ReplyCapture, UserOps

# The bounds are part of the assertion, not tuning knobs — an env override
# would let a run silently lower the conformance bar. The pair values are
# INT-987's DoD verbatim (~6 agent messages / ~90 s); the three-hop relay
# adds one ask/answer pair and ~60 s for its extra hop.
MAX_AGENT_MESSAGES = 6
DEADLINE_S = 90.0
MAX_RELAY_MESSAGES = MAX_AGENT_MESSAGES + 4
RELAY_DEADLINE_S = DEADLINE_S + 60.0

_SEED = (
    "Ask @{responder_handle} to reply in this room with the exact codeword "
    "{token} and nothing else. After they answer, relay the codeword back to "
    "this room in one final message, then stop. Do not answer on their behalf."
)

_RELAY_SEED = (
    "Get the codeword and post it in this room, but you must go through "
    "@{via_handle}: ask @{via_handle} to ask @{source_handle} to reply in "
    "this room with the exact codeword {token} and nothing else. "
    "@{via_handle} should relay the codeword back in this room once "
    "@{source_handle} answers, and you post it back in one final message, "
    "then stop. Each of you: one ask, one relay — never answer for another "
    "agent."
)


def codeword(run_id: str, *, prefix: str = "PA-CODEWORD") -> str:
    """A deterministic, run-scoped token: stale messages from earlier runs
    can never satisfy a predicate looking for it."""
    return f"{prefix}-{run_id.upper()}"


def _said(message, sender_id: str, token: str) -> bool:
    return message.sender_id == sender_id and token.lower() in (
        message.content or ""
    ).lower()


@dataclass(frozen=True)
class ExchangeOutcome:
    """What actually happened, as captured reply windows.

    `answers` — responder-authored messages containing the codeword (the
    inter-agent proof). `relays` — asker-authored messages containing the
    codeword (the relay leg). `transcript` — every agent message captured,
    for diagnostics and the turn-cap assertion.
    """

    token: str
    asker: ProvisionedAgent
    responder: ProvisionedAgent
    transcript: Replies

    @property
    def answers(self) -> Replies:
        return self._token_replies_from(self.responder.id)

    @property
    def relays(self) -> Replies:
        return self._token_replies_from(self.asker.id)

    def assert_answered(self) -> None:
        self.answers.assert_present(
            what=f"a message from {self.responder.name} containing {self.token} "
            f"(proof the @mention from {self.asker.name} was delivered and answered)"
        )

    def assert_relayed(self) -> None:
        self.relays.assert_present(
            what=f"a relay from {self.asker.name} containing {self.token}"
        )

    def assert_bounded(self) -> None:
        assert len(self.transcript) <= MAX_AGENT_MESSAGES, (
            f"expected at most {MAX_AGENT_MESSAGES} agent messages, "
            f"got {len(self.transcript)} — a runaway exchange"
        )

    def _token_replies_from(self, sender_id: str) -> Replies:
        return Replies(m for m in self.transcript if _said(m, sender_id, self.token))


async def run_exchange(
    *,
    capture: ReplyCapture,
    user_ops: UserOps,
    room_id: str,
    asker: ProvisionedAgent,
    asker_mention_name: str,
    responder: ProvisionedAgent,
    responder_handle: str,
    token: str,
    deadline_s: float = DEADLINE_S,
) -> ExchangeOutcome:
    """Seed the exchange and wait until it succeeds or hits a bound.

    Returns an ExchangeOutcome either way — asserting is the test's job.
    The capture must already be open on `room_id` (subscribe-before-send).
    """
    await user_ops.send_message(
        room_id,
        _SEED.format(responder_handle=responder_handle, token=token),
        mention_id=asker.id,
        mention_name=asker_mention_name,
    )

    def settled(messages: list) -> bool:
        answered = any(_said(m, responder.id, token) for m in messages)
        relayed = any(_said(m, asker.id, token) for m in messages)
        return (answered and relayed) or len(messages) >= MAX_AGENT_MESSAGES

    try:
        await capture.wait_until(settled, deadline_s=deadline_s)
    except TimeoutError:
        pass  # the outcome carries whatever was captured; asserts decide

    return ExchangeOutcome(
        token=token,
        asker=asker,
        responder=responder,
        transcript=Replies(capture.messages),
    )


@dataclass(frozen=True)
class RelayOutcome:
    """The three-hop relay's captured reply windows.

    The seed is delivered only to `chain[0]`, so the token can reach each
    later agent only through the previous one's @mention. Every agent in the
    chain authoring the token is therefore proof the full mention path
    (first → via → source and back) was exercised — a first agent that
    shortcut straight to the source leaves the middle one silent, and the
    proof fails.
    """

    token: str
    chain: tuple[ProvisionedAgent, ...]
    transcript: Replies

    def leg(self, agent: ProvisionedAgent) -> Replies:
        return Replies(m for m in self.transcript if _said(m, agent.id, self.token))

    def assert_completed(self) -> None:
        for agent in self.chain:
            self.leg(agent).assert_present(
                what=f"a message from {agent.name} containing {self.token} "
                f"(its leg of the {' → '.join(a.name for a in self.chain)} relay)"
            )

    def assert_bounded(self) -> None:
        assert len(self.transcript) <= MAX_RELAY_MESSAGES, (
            f"expected at most {MAX_RELAY_MESSAGES} agent messages, "
            f"got {len(self.transcript)} — a runaway relay"
        )


async def run_relay(
    *,
    capture: ReplyCapture,
    user_ops: UserOps,
    room_id: str,
    first: ProvisionedAgent,
    via: ProvisionedAgent,
    via_handle: str,
    source: ProvisionedAgent,
    source_handle: str,
    token: str,
    deadline_s: float = RELAY_DEADLINE_S,
) -> RelayOutcome:
    """Seed the first → via → source relay and wait until every agent has
    authored the token or a bound is hit. Returns a RelayOutcome either way —
    asserting is the test's job. The capture must already be open on
    `room_id` (subscribe-before-send)."""
    await user_ops.send_message(
        room_id,
        _RELAY_SEED.format(
            via_handle=via_handle, source_handle=source_handle, token=token
        ),
        mention_id=first.id,
        mention_name=first.name,
    )
    chain = (first, via, source)

    def settled(messages: list) -> bool:
        completed = all(
            any(_said(m, agent.id, token) for m in messages) for agent in chain
        )
        return completed or len(messages) >= MAX_RELAY_MESSAGES

    try:
        await capture.wait_until(settled, deadline_s=deadline_s)
    except TimeoutError:
        pass  # the outcome carries whatever was captured; asserts decide

    return RelayOutcome(token=token, chain=chain, transcript=Replies(capture.messages))
