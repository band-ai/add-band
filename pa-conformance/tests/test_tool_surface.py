"""T1 tool surface: what the harness offers its model, and whether a model
decision dispatches through the harness's real loop.

The namespace and coexistence rows read a scripted turn's ModelCall.tools — the
tool surface exactly as declared on the provider wire. The dispatch row is the
INT-800 contract's PA translation end-to-end: a scripted tool call must land on
the harness's real tool (a Band read against the live platform), proven by the
follow-up request's tool_result naming this room's participant.

All rows gate on the Profile model_wire verdict (the INT-986 N-A rule);
PA_STANDIN=off skips too.
"""

from __future__ import annotations

import pytest

from conftest import OwnerChatFactory
from driver.exchange import marker
from driver.standin import decision
from harness import HARNESS
from harness.contract import PROFILE_FIELD

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_profile(PROFILE_FIELD.model_wire),
]


@pytest.mark.requires_profile(PROFILE_FIELD.tool_namespace)
async def test_band_tools_namespaced_without_collision(
    pa, owner_chat: OwnerChatFactory, run_id: str
) -> None:
    """L0a: a required Band tool reaches the model under the harness's declared
    namespace, and the tool surface is collision-free — no name appears twice.
    band_get_participants is the probe: every harness offers it, so asserting
    its *full* name carries the namespace proves Band tools are namespaced, not
    merely that some prefixed tool exists."""
    namespace = pa.profile.tool_namespace
    async with owner_chat(pa) as chat:
        call = await chat.ask_scripted(token=marker(run_id, prefix="PA-T1-NS"))

    required = call.tool_ending("band_get_participants")
    assert required, (
        f"{pa.harness.name} offers no band_get_participants; "
        f"wire tools: {call.tool_names}"
    )
    assert required.name.startswith(namespace), (
        f"{pa.harness.name}'s Band tool {required.name!r} is not under the "
        f"declared namespace {namespace!r}"
    )
    assert not call.duplicate_tool_names(), (
        f"{pa.harness.name} composed a colliding tool surface: "
        f"{call.duplicate_tool_names()}"
    )


@pytest.mark.requires_profile(PROFILE_FIELD.tool_namespace, PROFILE_FIELD.native_tool)
async def test_native_tools_coexist_with_band_tools(
    pa, owner_chat: OwnerChatFactory, run_id: str
) -> None:
    """L1: Band's tools are additive — a specific native tool the harness
    declares (profile.native_tool) survives alongside them. Asserting the named
    tool, not merely "something outside the namespace," so an un-namespaced
    Band tool can't masquerade as native coexistence."""
    native = pa.profile.native_tool
    async with owner_chat(pa) as chat:
        call = await chat.ask_scripted(token=marker(run_id, prefix="PA-T1-COEX"))

    assert native in call.tool_names, (
        f"{pa.harness.name}'s native tool {native!r} is absent — the native "
        f"surface was clobbered; wire tools: {call.tool_names}"
    )


@pytest.mark.requires_profile(PROFILE_FIELD.tool_namespace)
@pytest.mark.known_gap(
    HARNESS.hermes,
    reason="INT-990: the Band adapter raises 'Event is bound to a different "
    "event loop' when a tool runs on the agent's executor loop — the "
    "participant-fetch path INT-899 left unguarded when it fixed only send() — "
    "so the dispatched band_get_participants returns an error not participants; "
    "the seam drives the tool, the upstream adapter bug breaks it",
    intermittent=True,
)
async def test_scripted_tool_call_dispatches_through_real_loop(
    pa, owner_chat: OwnerChatFactory, run_id: str
) -> None:
    """T1 dispatch: a scripted tool call lands on the right tool with the right
    args, executed by the harness's real loop against live Band — the follow-up
    request's tool_result names this room's participant. Turn 1 reads the tool
    surface; the target tool and its room argument come from the harness's own
    declared schema, never hand-listed per harness."""
    async with owner_chat(pa) as chat:
        surface = await chat.ask_scripted(token=marker(run_id, prefix="PA-T1-SURFACE"))
        tool = surface.tool_ending("band_get_participants")
        assert tool, (
            f"{pa.harness.name} offers no band_get_participants tool; "
            f"wire tools: {surface.tool_names}"
        )
        call = await chat.dispatch(
            tool,
            room=chat.room_id,
            token=marker(run_id, prefix="PA-T1-DISPATCH"),
            follow_up=decision(text="The tool result was received."),
        )

    assert call.tool_results(), (
        f"{pa.harness.name} never reported a tool_result for the scripted tool "
        f"call; follow-up messages: {str(call.messages)[-500:]}"
    )
    assert call.tool_result_names(pa.agent), (
        f"{pa.harness.name} dispatched {tool.name} but the result names no "
        f"participant of this room: {call.tool_results()}"
    )
