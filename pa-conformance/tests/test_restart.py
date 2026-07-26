"""L4 restart / rehydration: a bounced PA reloads its persisted state,
reconnects without re-provisioning, and handles the messages that arrived
while it was down.

Every scenario drives the store-preserving restart verbs (harness/contract.py:
stop/start/restart bounce only the PA runtime; datastores and persisted state
survive) through the PA async wrappers, and proves rehydration behaviorally —
a post-restart answer in a pre-restart room IS the store surviving; no
store-inspection API is involved.

Reconnection, known-room reattachment, offline-message handling, and strict thread recovery
(the post-restart turn's composed model context, read from the stand-in's
recording) are covered here. Conversation continuity can be restored through a
transcript, summary, or retrieval policy, so the wire-level transcript row is
capability-gated rather than inferred from an LLM recall answer. The degraded-
credentials row is toolkit-supported (corrupt/restore_platform_creds) but
deliberately carries no test: observing "degraded" differs per harness.
ID-level idempotency needs a platform stand-in (Band mints message ids);
hub-identity rows need the Profile hub key's F1 round (INT-892).

Platform doctrine that shapes these tests: every user message must mention
someone (unmentioned sends are rejected with 422) and Band delivers only to
the mentioned agents — so "a message the PA must not process" is one that
mentions a harness-less decoy agent, and absence is asserted as
token-never-appears once an addressed control turn settles the window (the
visibility-matrix shape).
"""

from __future__ import annotations

import pytest

from conftest import OwnerChatFactory
from driver.exchange import liveness_name, marker
from harness import HARNESS
from harness.contract import PROFILE_FIELD
from driver.sdk import DeliveryStatus, ResourceManager, UserOps
from driver.waits import said_by

pytestmark = pytest.mark.e2e


@pytest.fixture
async def pa(pa):
    """The suite's pa, plus teardown insurance: harnesses are session-scoped
    and shared, so a failed restart test must not leave its runtime down for
    the tests that follow. start() on a running stack is a no-op."""
    yield pa
    await pa.start()
    await pa.wait_ready()


async def test_reconnects_and_serves_known_room(
    pa, owner_chat: OwnerChatFactory, run_id: str
) -> None:
    """Restart, recover readiness, and answer in a room attached before the
    bounce — attach_room is never run again, so the post-restart reply proves
    both the reconnection and that the room wiring rehydrated from the
    persisted store."""
    pre = liveness_name(run_id, salt="l4-pre")
    post = liveness_name(run_id, salt="l4-post")

    async with owner_chat(pa) as chat:
        (await chat.ask(token=pre)).assert_contains_any([pre])
        await pa.restart_and_wait_ready()
        recovered = await chat.ask(token=post)

    recovered.assert_contains_any([post])


@pytest.mark.flaky_harness(HARNESS.openclaw, reruns=2)
async def test_message_for_another_agent_sent_while_down_stays_unprocessed(
    pa,
    owner_chat: OwnerChatFactory,
    user_ops: UserOps,
    resources: ResourceManager,
    run_id: str,
) -> None:
    """A turn that never mentioned the PA, sent during its down-window, must
    not be retroactively processed on rehydration — a reconnect that scrapes
    room history and answers unaddressed turns would surface here. The
    mention target is a provisioned decoy agent with no harness behind it."""
    base = liveness_name(run_id, salt="l4-base")
    ghost = marker(run_id, prefix="PA-L4-GHOST")
    control = liveness_name(run_id, salt="l4-ctrl")
    # Named per harness: provisioned agent names are run-scoped, and every
    # harness param provisions its own decoy in the same session.
    decoy = await resources.provision_agent(f"restart-decoy-{pa.harness.name}")

    async with owner_chat(pa) as chat:
        await user_ops.add_participant(chat.room_id, decoy.id)
        (await chat.ask(token=base)).assert_contains_any([base])

        await pa.stop()
        await user_ops.send_message(
            chat.room_id,
            f"Note for you only: the marker is {ghost}. Reply with it.",
            mention_id=decoy.id,
            mention_name=decoy.name,
        )
        await pa.start()
        await pa.wait_ready()

        (await chat.ask(token=control)).assert_contains_any([control])
        leaked = said_by(chat.room, pa.agent.id, ghost, excluding=control)

    assert not leaked, (
        f"{pa.harness.name} processed a turn addressed to another agent "
        f"while it was down: {[m.content for m in leaked]}"
    )


@pytest.mark.requires_profile(PROFILE_FIELD.emits_processed)
@pytest.mark.known_gap(
    HARNESS.hermes,
    reason="INT-1003: hermes re-processes the offline turn after a gateway "
    "restart (startup-restore replays completed work), so it lands PROCESSED "
    "twice",
    intermittent=True,
)
@pytest.mark.known_gap(
    HARNESS.nanoclaw,
    reason="INT-1004: nanoclaw re-delivers an already-processed turn to a fresh "
    "session after a host restart, so it lands PROCESSED twice",
    intermittent=True,
)
async def test_addressed_message_sent_while_down_processed_exactly_once(
    pa, owner_chat: OwnerChatFactory, run_id: str
) -> None:
    """A turn addressed to the PA during its down-window is processed exactly
    once after rehydration — judged by the platform's own delivery-status
    lifecycle, not reply text: PROCESSED reached, once, and nothing after it.
    The addressed control turn gives a would-be duplicate time to surface
    before the history is judged."""
    token = marker(run_id, prefix="PA-L4-OFFLINE")

    async with owner_chat(pa) as chat:
        await pa.stop()
        offline_mid = await chat.send(
            prompt=f"Owner note delivered while you were offline (ref {token}); "
            "acknowledge it now that you are back."
        )
        await pa.start()
        await pa.wait_ready()

        await chat.room.wait_for_processed(offline_mid, pa.agent.id)
        # A benign readiness turn settles the window without asking the PA to
        # echo an opaque token — a security-hardened harness (Hermes) refuses
        # that as a credential challenge, and the invariant here is the
        # platform's PROCESSED count, not any reply text.
        (
            await chat.ask(
                token="ONLINE",
                prompt="Reply with only the word ONLINE to confirm you are back up.",
            )
        ).assert_present(what=f"a readiness reply from {pa.harness.name}")

        history = chat.room.delivery_history(offline_mid, pa.agent.id)

    assert history.count(DeliveryStatus.PROCESSED) == 1, (
        f"{pa.harness.name} processed the offline message more than once: "
        f"{history}"
    )


@pytest.mark.known_gap(
    HARNESS.hermes,
    reason="INT-1003: hermes re-answers the already-answered last turn after "
    "a gateway restart (startup-restore replays completed work)",
    intermittent=True,
)
@pytest.mark.known_gap(
    HARNESS.nanoclaw,
    reason="INT-1004: nanoclaw re-delivers an already-answered turn to a "
    "fresh session after a host restart (duplicate reply + re-greeting)",
    intermittent=True,
)
async def test_processed_turn_not_reanswered_after_restart(
    pa, owner_chat: OwnerChatFactory, run_id: str
) -> None:
    """A turn answered before the restart is not answered again after it — a
    runtime that replays its queue or re-fires completed work on rehydration
    would author a second token-bearing reply. Reply presence is the
    harness-neutral observable; tool-call-level idempotency needs the Tier-1
    injection seam (INT-986). Replies carrying the control token are excluded
    so a reply quoting earlier context cannot false-positive."""
    token = liveness_name(run_id, salt="l4-once")
    control = liveness_name(run_id, salt="l4-reanswer-ctrl")

    async with owner_chat(pa) as chat:
        (await chat.ask(token=token)).assert_contains_any([token])
        settled = chat.settled

        await pa.restart_and_wait_ready()

        (await chat.ask(token=control)).assert_contains_any([control])
        reanswered = said_by(
            chat.room, pa.agent.id, token, since=settled, excluding=control
        )

    assert not reanswered, (
        f"{pa.harness.name} re-answered an already-processed turn after "
        f"restart: {[m.content for m in reanswered]}"
    )


@pytest.mark.requires_profile(
    PROFILE_FIELD.model_wire, PROFILE_FIELD.rehydrates_thread_after_restart
)
async def test_thread_recovery_carries_prior_transcript(
    pa, owner_chat: OwnerChatFactory, run_id: str
) -> None:
    """L4 strict thread recovery: after a restart, the next turn's composed
    model context carries THIS room's pre-restart content — the transcript
    recovered into the same thread, observed on the model wire instead of
    inferred from a recall answer. The marker is room-specific, so merely
    rendering *some* history cannot pass. The stand-in is not a restart
    service, so its recording survives the bounce.

    The markers ride along as passive room content (seeded via a benign
    STORED/BACK acknowledgement) rather than being echoed back verbatim: the
    pre-restart marker only needs to be in this room's transcript, and the
    post-restart marker only needs to reach the model wire — asking a
    security-hardened harness to parrot an opaque token trips its
    prompt-injection guard."""
    pre = marker(run_id, prefix="PA-L4-WIRE-PRE")
    post = marker(run_id, prefix="PA-L4-WIRE-POST")

    async with owner_chat(pa) as chat:
        seeded = await chat.ask(
            token="STORED",
            prompt=f"Remember this room's marker: {pre}. Reply with only the "
            "word STORED once you have it.",
        )
        seeded.assert_present(what=f"a marker seed from {pa.harness.name}")
        await pa.restart_and_wait_ready()
        await chat.ask(
            token="BACK",
            prompt=f"Post-restart check {post}: reply with only the word BACK "
            "to confirm you are back online.",
        )
        call = await chat.recorded_call(carrying=post, agent_loop=True)

    assert call.carries(pre), (
        f"{pa.harness.name} composed the post-restart turn without this "
        f"room's pre-restart content ({pre} absent) — the thread did not "
        "recover strictly"
    )
