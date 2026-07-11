"""Phase-0 wait primitives on top of the SDK capture.

The toolkit's `ReplyCapture.wait_for_reply` barriers on the platform's
PROCESSED delivery status before looking at reply frames. That status is
emitted by the harness's Band client, and not every harness reports it
(live-observed: Hermes does, OpenClaw's channel plugin does not — its
messages stay at `none` even after it visibly replies). Delivery-status
conformance is a later-phase, per-level concern; Phase-0 liveness is
"a reply came back", so these waits are reply-presence-based and
harness-neutral — still event-driven over the WS capture, no polling.

Both waits are best-effort: on the deadline they return whatever matched
rather than raising, so the caller's declarative assertion (assert_present /
assert_contains_any) is what fails — naming the harness and the missing
behavior — instead of a bare TimeoutError from deep in the capture.
"""

from __future__ import annotations

from collections.abc import Sequence

from driver.sdk import Replies, ReplyCapture


def _authored(message, sender_id: str, containing: str | None) -> bool:
    return message.sender_id == sender_id and (
        containing is None or containing.lower() in (message.content or "").lower()
    )


async def wait_for_reply_from(
    capture: ReplyCapture,
    sender_id: str,
    *,
    since: int = 0,
    containing: str | None = None,
    deadline_s: float | None = None,
) -> Replies:
    """Wait for a message authored by `sender_id` (optionally carrying
    `containing`) at buffer index `since` or later; return that sender's
    replies from the window.

    `since` scopes the wait to the current turn of a multi-turn test — mark
    `len(capture.messages)` once the previous turn has settled — so an earlier
    turn's reply can never satisfy a later turn's wait. `containing` waits for
    the message that proves the behavior, not merely the first one: a sender's
    first message is not always the answer (live-observed, Hermes posts an
    interim "interrupting current task" notice before replying)."""
    try:
        await capture.wait_until(
            lambda msgs: any(
                _authored(m, sender_id, containing) for m in msgs[since:]
            ),
            deadline_s=deadline_s,
        )
    except TimeoutError:
        pass  # best-effort: the caller's assertion reports the miss
    return Replies(m for m in capture.messages[since:] if m.sender_id == sender_id)


async def wait_for_replies_from(
    capture: ReplyCapture,
    sender_ids: Sequence[str],
    *,
    containing: str | None = None,
    deadline_s: float | None = None,
) -> dict[str, Replies]:
    """Wait until every sender in `sender_ids` has authored a matching message
    (the fan-out settling condition); return the matching replies keyed by
    sender id. With `containing`, a sender only counts once it produces a
    reply carrying that token, so an interim/non-answer message does not
    satisfy the wait and the empty entry names the silent sender."""
    pending = list(sender_ids)
    try:
        await capture.wait_until(
            lambda msgs: all(
                any(_authored(m, sender, containing) for m in msgs)
                for sender in pending
            ),
            deadline_s=deadline_s,
        )
    except TimeoutError:
        pass  # best-effort: per-sender assertions report which stayed silent
    return {
        sender: Replies(
            m for m in capture.messages if _authored(m, sender, containing)
        )
        for sender in pending
    }
