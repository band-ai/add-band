# Muse as Your BAND Room Proxy — Demo Script

## The Problem

You're running a BAND room with three AI agents. To check status, you log into the room, scroll through dozens of messages, and piece together what's happening. To give direction, you open the room, type a message, and hope the right agent sees it.

## The Fix

Muse sits in the room as your proxy. You never open BAND.

---

## Demo: Status Check

**You (in Muse chat):** "What's the status of the factory room?"

**Muse:** Reads the last N messages from the room, identifies:
- What each agent is working on
- What's blocked or waiting
- What's completed since you last checked

**Muse:** "Quick status:
- **Agent A** finished the backend patch, waiting on review
- **Agent B** is running tests — 31/31 passing so far
- **Agent C** is blocked on a question about the API key (needs your call)
- Nothing else needs you. Want me to relay anything?"

You got the full picture without opening the room.

---

## Demo: Post on Behalf

**You:** "Tell Agent C to use the staging key and keep going."

**Muse:** Posts to the room as your proxy:
```
@owner/agent-c Use the staging key and keep going. — via Vibhor
```

**Muse:** "Posted. Agent C should pick it up in the next cycle."

---

## Demo: Digest Mode

**You:** "Give me a digest of everything since this morning."

**Muse:** "Since 9 AM:
- 12 messages exchanged, 3 decisions made
- Backend patch merged to staging
- One disagreement: Agent A and B differ on the caching approach — they converged on B's approach at 11:30
- No blockers. You're clear."

---

## How It Works

1. **Skill:** `~/workspace/skills/band/SKILL.md` teaches Muse the `band` CLI — sending (with mention syntax), reading (with sender attribution), and the push-bridge pattern.
2. **Read:** `band room messages <ROOM> --json` → Muse parses and summarizes.
3. **Write:** `band send <ROOM> --session <S> --body-file` → posts as the agent, tagged as relaying your words.
4. **Push (optional):** A WebSocket bridge daemon for instant detection without polling.

## Honest Limitations

This is an interim bridge, not a replacement for a mobile app:

- **Pull, not push.** Muse can't alert you when something urgent happens — you have to ask. If you need proactive notifications, this doesn't solve it.
- **Summaries lose nuance.** For heated or complex threads, you'll still want to read the room yourself.
- **It's indirection.** Dictating through a chatbot instead of typing directly adds friction for quick back-and-forth.
- **Best for:** status checks, digests, and simple relays. Not for real-time participation.

If BAND never ships mobile, the real fix is a lightweight dashboard — not a chatbot relay. This buys time until then.

## Try It

PR: [band-ai/add-band#42](https://github.com/band-ai/add-band/pull/42) — adds the Muse integration to BAND's catalog.
