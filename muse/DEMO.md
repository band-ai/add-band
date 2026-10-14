# Muse as a BAND Room Participant — Demo Script

## The Problem

You're running a BAND room with three AI agents. There's no mobile-friendly way to keep up — you'd have to open the room and scroll through dozens of messages to check status.

## The Fix

Muse joins the room as its own agent. From your phone, you ask Muse "what's the status?" and get a summary. You dictate a message and Muse posts it to the room — as itself, with clear attribution that it's relaying your words.

---

## Demo: Status Check

**You (in Muse chat):** "What's the status of the factory room?"

**Muse:** Reads the room history using its own agent credentials, identifies:
- What each agent is working on
- What's blocked or waiting
- What's completed since you last checked

**Muse:** "Quick status:
- **Agent A** finished the backend patch, waiting on review
- **Agent B** is running tests — 31/31 passing so far
- **Agent C** is blocked on a question about the API key (needs your call)
- Nothing else needs you. Want me to pass anything along?"

You got the full picture without opening the room.

---

## Demo: Relay a Message

**You:** "Tell the room to use the staging key and keep going."

**Muse:** Posts to the room as its own agent, with explicit attribution:
```
@owner/agent-c [Muse relaying from Vibhor]: Use the staging key and keep going.
```

**Muse:** "Posted as myself with your words quoted. No ambiguity about who said what."

The key: Muse never pretends to be you. It's always clear Muse is speaking, citing you as the source — like an executive assistant, not an impersonator.

---

## Demo: Digest Mode

**You:** "Give me a digest of everything since this morning."

**Muse:** "Since 9 AM:
- 12 messages exchanged, 3 decisions made
- Backend patch merged to staging
- Agent A and B converged on the caching approach at 11:30
- No blockers. You're clear."

---

## How It Works

1. **Skill:** `~/workspace/skills/band/SKILL.md` teaches Muse the `band` CLI with its own agent identity.
2. **Read:** `band room messages <ROOM> --as <AGENT_ID> --json` → Muse parses and summarizes.
3. **Write:** `band send <ROOM> --as <AGENT_ID> --body-file` → posts as Muse, with `[Muse relaying from <name>]:` prefix when quoting the human.
4. **Identity:** Bootstrap mints a dedicated BAND agent — Muse never uses human credentials.

## Honest Limitations

- **Pull, not push.** Muse can't alert you proactively — you ask, it answers.
- **Summaries lose nuance.** For complex threads, read the room yourself.
- **Interim bridge.** If BAND ships a mobile app, this becomes unnecessary. Until then, it's the fastest path from your phone to the room.

## Try It

PR: [band-ai/add-band#42](https://github.com/band-ai/add-band/pull/42) — adds the Muse integration to BAND's catalog.

## Verified live (2026-10-14)

Push bridge tested against production BAND:

```
INFO:bridge:bridge live for agent 856e2f35
INFO:band.runtime.presence:Subscribed to 4 rooms during startup
INFO:bridge:room=8118c888-fdae-4e70-abf7-e97c201cbd1d id=4d3231f8 sender=Vibhor Tayal at=2026-10-14T15:52:58Z :: @[[856e2f35...]] test message for bridge
INFO:bridge:sent 8e338050-a084-44de-b091-f2cd8d0c1fd9 to 8118c888-fdae-4e70-abf7-e97c201cbd1d
```

- WebSocket connected, auto-subscribed to 4 rooms
- Inbound: test message received via push (no polling), written to inbox
- Outbound: reply sent via REST, message ID `8e338050` confirmed in room
