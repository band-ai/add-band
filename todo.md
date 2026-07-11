# PA conformance — test plan to finish INT-893

Parent task **INT-893** = turn the PA conformance ladder (INT-892, the L0–L6 +
F1–F4 doc) into a runnable per-harness scorecard. **INT-987 (Phase 0)** built
the live driver + runners and proved the hardest rung fragments end-to-end.
This file maps every test still owed and the work needed to make it executable.

Source of truth for the bars: `personal-agents-conformance-levels.md`
(product-docs-vault PR #141). Each rung there gives a **pass bar**, a **tier**,
and **per-harness profile fields** — this plan is the executable projection.

## Legend

- **Tier 1** — deterministic, no live LLM: supply a delivered turn / transcript
  / persisted store to a stand-in, inspect resulting state. Runs on every PR.
- **E2E** — a real model decides (route, recall, call a tool, answer). What
  Phase 0 does today; live-only, on demand.
- Status: ✅ done · 🟡 partial (E2E only, or one harness) · ⬜ not started.

## Cross-cutting foundations

- ⬜ **Per-harness conformance profile** — candidate INT-893 sub-issue. Declare
  the fields each rung requires per harness: namespace format, hub identity key,
  ordering fallback, idempotency scheme, read-point observable-vs-E2E, and so
  on. Drives which tests run T1 vs E2E-only. This is the highest-leverage
  missing piece because every level references it.
- ⬜ **Tier-1 injection/observation seam** — candidate INT-893 sub-issue. Supply
  a delivered turn and read the composed context/tool set without a live model.
  Tracks **INT-986** (SDK Tier-1 seam) and **INT-800** (Tier-1 injection
  contract). Until the seam exists, every resulting-state check below is
  **E2E-only**.
- ⬜ **Scorecard emission** — candidate INT-893 sub-issue. Emit per-harness ×
  per-level pass/fail/N-A(+reason), in the adapter-scorecard shape (mirror
  INT-820). Feeds **INT-894** (CI).
- 🟡 **Result presentation** — the `/pa-conformance` skill asks for a
  harness×scenario matrix after a run; wire it to the real scorecard once it
  exists.

## L0a — Band layer present

- ⬜ **T1** Band platform prompt present in composed context (per profile read
  point; E2E-only where none).
- ⬜ **T1** Band tool names namespaced — no collision across platforms.
- ⬜ **T1** Band event carries platform identity (attributable to Band).
- ⬜ **T1** room + participants render into per-turn context.
- ✅ **E2E** agent answers a specific Band turn — `test_liveness` requires a
  run-scoped reply token, not a generic acknowledgement.

## F1 — Owner hub & command gate  (control plane)

- ⬜ **T1** first connect → exactly one owner-only hub (owner + agent, nobody
  else).
- ⬜ **T1** re-connect under the same hub identity key → resolves to existing
  hub, no duplicate.
- ⬜ **T1** owner `/command` executes.
- ⬜ **T1** non-owner `/command` refused per the declared policy (ignore vs
  reject) — never executed.

## L1 — Additive coexistence (system prompt & native tools)

- ⬜ **T1/E2E** system prompt present and not replaced by Band's platform
  prompt.
- ⬜ **T1/E2E** native tools (if the harness has them) not clobbered by Band's
  tools.
- ⬜ **T1/E2E** Band prompt/tools present and additive.
- Note: coexistence is T1 where the composed context is inspectable, else
  E2E-only; system-prompt *effect on output* is always E2E.

## L2 — Conversation context fidelity

- ⬜ **T1** same logical conversation → same agent thread (per declared
  conversation-identity key).
- ⬜ **T1** distinct conversations separate/shared per configured topology;
  hub vs group and Band vs non-Band no accidental fusion.
- ⬜ **T1** ordering normalized to server order, or a declared deterministic
  fallback where Band gives no order signal.
- ⬜ **T1** attribution preserved — PA's own prior replies not reclassified as
  user turns.
- ⬜ **T1** divergence resolves to a declared outcome (Band-wins /
  last-writer-wins / reconcile-and-flag); silent corruption = fail.
- ✅ **E2E** recall a fact from an earlier turn — `test_memory` requires a
  combined token whose random suffix appears only in turn two, so a delayed
  first-turn reply cannot satisfy it.

## L3 — Multi-participant chat

- ⬜ **T1** mention trim: `@agent /x` → `/x` runs; `@agent hello` → clean
  prompt; meaningful later-in-message mentions preserved.
- ⬜ **T1** identity discrimination: owner / non-owner / self / other agents;
  other agents' messages not treated as the PA's own prior turns.
- ⬜ **T1** non-owner `/command` still blocked when it mentions the agent.
- ⬜ **T1** non-owner plain prompt admitted/ignored per declared policy.
- 🟡 **T1/E2E** roster + attributed multi-author history present in context —
  `test_multi_author_history_preserves_sender_identity` covers the E2E proof;
  the deterministic composed-context assertion remains.
- 🟡 **T1** outbound turn carries the target's Band `@handle` (not display
  name) — pair and relay E2E proofs require the handle in the structured
  outbound mention; the deterministic assertion remains.
- ✅ **E2E** actual routing / delegation — group fan-out, attributed
  multi-author history, and pair/three-way relays. Relay proofs require ordered
  sender steps, structured target mentions, and the target's full `@handle`.
- N-A: co-resident *processes* on one host (single owned runtime).

## L4 — Restart / rehydration (four facets)

- ⬜ **T1** platform reconnection: valid persisted creds reload, no
  re-onboard; absent/invalid creds → declared non-crashing degraded state.
- ⬜ **T1** channel-topology recovery: known rooms reattached; hub found by
  identity key; if gone, exactly one replacement; valid hub not duplicated.
- ⬜ **T1** thread recovery: transcript maps back to the same thread; topology
  preserved; addressed offline messages processed exactly once; un-routed
  messages not retroactively processed.
- ⬜ **T1** idempotency: handled message IDs / completed command IDs /
  completed tool-call IDs (declared scheme) — no re-answer, re-run, or
  re-fired side-effect.
- ⬜ **E2E** hydrated history actually used to answer; completed side-effect
  not re-firing against live Band.
- Needs a restart primitive in the runner contract (`restart()` exists on the
  compose wrapper; add a harness-level cold-start verb + persisted-store
  fixtures).

## F4 — Onboarding & publishing (gate)

- 🟡 **T1** connect + hub-provision via the published path — the bootstraps
  and the `add-band` skills exist; needs a conformance check that following
  the guide reaches "connected + hub up".
- ⬜ **E2E** end-to-end "responds on Band" smoke from a clean onboard.

## L5 — Memory & contacts (+ F3 cross-platform control)

- ⬜ **T1** contacts tool-call dispatch (canonical L5 bar, no inversion).
- ⬜ **E2E** contact actually created / listed on Band.
- ⬜ **T1** shared-memory integration dispatch (asked-for; per profile shape).
- ⬜ **E2E** memory persisted to the shared cross-agent store.
- ⬜ **F3 T1** dispatch a Band side-effect from a non-Band platform (supplied
  decision).
- ⬜ **F3 E2E** request on platform X → correct Band side-effect and/or
  accurate Band-state answer back on X. Needs a second connected platform in
  the harness (profile declares which).

## L6 — Session activity events

- ⬜ **T1** all event types (thoughts / execution / task) emitted to an event
  stand-in in the right shapes.
- ⬜ **E2E** events visible in the live Band session.
- ⬜ Per harness: task-event N-A + recorded reason where the framework has no
  task concept.

## Sequencing

1. **Profile schema first** — nothing scores comparably without it; it decides
   every T1-vs-E2E split below.
2. **Tier-1 seam** (tracks INT-986/INT-800) — unlocks the deterministic half;
   until then land the E2E rungs and mark T1 checks E2E-only in the profile.
3. **Deepen what Phase 0 started** — ✅ liveness→L0a, memory→L2, and
   exchanges→L3 have sound E2E proofs. Add Tier-1 cases as upstream seams make
   each declared check observable.
4. **L4 restart** — needs the cold-start verb + persisted-store fixtures.
5. **L5/F3, L6** — need capability tools and a second platform (F3).
6. **Scorecard + CI** — emit per-harness×level, wire into INT-894.
