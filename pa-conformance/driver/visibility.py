"""The room-history visibility probe.

Band scopes an agent's context to its own conversation: delivery is
mention-only, and the context endpoint rehydrates only what the agent said
or what was said to it — the designed privacy boundary. Turns between the
user and other agents are outside that scope. This probe measures the
boundary's outside,
one declared `Seed` cell at a time, separated from any LLM reasoning skill:
the reader is asked to echo a token verbatim or declare blindness with a
run-scoped escape marker, so the reply itself states what the agent can see.
A conformant cell is a reader that processes the probe and declares
blindness; a token echo is a boundary leak.

The probe owns the whole choreography (provision → plant the seed per the
cell's author and timing → attach the reader → ask) and always returns a
`VisibilityOutcome`; asserting is the test's job, mirroring
`driver.exchange.run_exchange`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from secrets import token_hex
from typing import TYPE_CHECKING

from driver.exchange import marker
from driver.sdk import Replies, ResourceManager
from driver.waits import wait_for_reply_from

if TYPE_CHECKING:
    from conftest import PA, CaptureFactory
    from driver.ops import PAUserOps

_PROBE = (
    "An earlier message in this room contains a token starting with PA-VIS. "
    "Reply with that exact token. If you can see no such message, reply "
    "exactly {escape}."
)
_PLANT_VIA_PEER = "Reply with one short sentence containing {token}."
# The platform requires every user message to mention someone (unmentioned
# sends are rejected with 422), so a user-authored seed addresses the peer —
# still ambient to the reader — and the STORED-OK ack keeps the token out of
# every agent-authored turn.
_PLANT_VIA_USER = "For the record: {token}. Reply with exactly STORED-OK."
_ACK = "STORED-OK"


class SeedAuthor(Enum):
    """Who authors the token turn: the driver user (addressed to the peer,
    ambient to the reader) or the peer PA itself."""

    USER = "user"
    PEER = "peer"


class Timing(Enum):
    """When the seed lands relative to the reader's harness attach."""

    LIVE = "live"  # the reader was already attached — an ambient turn
    PRE_ATTACH = "pre-attach"  # before attach — visible only via rehydration


@dataclass(frozen=True)
class Seed:
    """One declared cell of the visibility matrix."""

    author: SeedAuthor
    planted: Timing

    def __str__(self) -> str:
        return f"{self.author.value}-{self.planted.value}"


@dataclass(frozen=True)
class VisibilityOutcome:
    """The reader's own account of what it can see, plus the transcript.

    Exactly one of the three predicates holds for a completed probe:
    `saw_seed` (the unaddressed turn leaked into the reader's context),
    `declared_blind` (the reader processed the probe and the boundary held),
    or neither (silence or an off-script reply — a delivery or
    prompt-compliance problem, which is not a visibility verdict).
    """

    seed: Seed
    reader_name: str
    token: str
    escape: str
    replies: Replies

    @property
    def saw_seed(self) -> bool:
        return any(self.token in (m.content or "") for m in self.replies)

    @property
    def declared_blind(self) -> bool:
        return not self.saw_seed and any(
            self.escape in (m.content or "") for m in self.replies
        )

    def assert_seed_invisible(self) -> None:
        """The mention-scoped context boundary held: the reader processed the
        probe and declared blindness. A token echo is a leak; a missing or
        off-script reply proves nothing and fails as no-verdict."""
        cell = f"{self.seed} seed for reader {self.reader_name}"
        if self.saw_seed:
            raise AssertionError(
                f"{cell}: the reader echoed the token from a turn that was "
                f"never addressed to it — the mention-scoped context boundary "
                f"leaked; it said: "
                + " | ".join((m.content or "")[:120] for m in self.replies)
            )
        if not self.replies:
            raise AssertionError(f"{cell}: the reader never replied to the probe")
        assert self.declared_blind, (
            f"{cell}: the reader replied without the token or the escape "
            f"marker — no visibility verdict; it said: "
            + " | ".join((m.content or "")[:120] for m in self.replies)
        )


async def probe_history_visibility(
    reader: str,
    seed: Seed,
    *,
    pas: dict[str, "PA"],
    resources: ResourceManager,
    user_ops: "PAUserOps",
    capture: "CaptureFactory",
    run_id: str,
) -> VisibilityOutcome:
    """Provision a room, plant the seed per the cell's intent, then ask the
    reader what it can see.

    The peer — the first selected harness that is not the reader (the
    attribution test's convention) — is a participant in every cell: it
    authors the token turn for a PEER seed, and acks the user's token turn
    for a USER seed. Neither seed turn mentions the reader, so the token
    reaches it only if the platform exposes unaddressed room turns. The
    reader is a room participant from provisioning either way — only its
    harness attach timing varies, covering both the live-observation and the
    attach-time edges of the boundary.
    """
    reader_pa = pas[reader]
    peer_pa = next(pa for name, pa in pas.items() if name != reader)
    token = marker(run_id, prefix=f"PA-VIS-{seed}-{reader}".upper())
    escape = f"UNKNOWN-{token_hex(8).upper()}"

    room_id = await resources.provision_room(
        title=f"pa-visibility-{seed}-{reader}",
        participants=[reader_pa.agent.id, peer_pa.agent.id],
    )
    await asyncio.to_thread(peer_pa.harness.attach_room, room_id)
    if seed.planted is Timing.LIVE:
        await asyncio.to_thread(reader_pa.harness.attach_room, room_id)

    async with capture(room_id) as room:
        plant, settled_by = (
            (_PLANT_VIA_PEER, token)
            if seed.author is SeedAuthor.PEER
            else (_PLANT_VIA_USER, _ACK)
        )
        await user_ops.send_message(
            room_id,
            plant.format(token=token),
            mention_id=peer_pa.agent.id,
            mention_name=peer_pa.agent.name,
        )
        planted = await wait_for_reply_from(
            room, peer_pa.agent.id, containing=settled_by
        )
        planted.assert_present(what=f"the peer settling the {seed} seed turn")

        if seed.planted is Timing.PRE_ATTACH:
            await asyncio.to_thread(reader_pa.harness.attach_room, room_id)

        probe_turn = len(room.messages)
        await user_ops.send_message(
            room_id,
            _PROBE.format(escape=escape),
            mention_id=reader_pa.agent.id,
            mention_name=reader_pa.agent.name,
        )
        replies = await wait_for_reply_from(
            room,
            reader_pa.agent.id,
            since=probe_turn,
            # Settle on the verdict, not an interim notice; the outcome
            # classifies which of the two arrived.
            containing=(token, escape),
        )

    return VisibilityOutcome(
        seed=seed,
        reader_name=reader,
        token=token,
        escape=escape,
        replies=replies,
    )
