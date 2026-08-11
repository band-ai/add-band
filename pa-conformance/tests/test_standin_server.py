"""Hermetic tests for the model stand-in (stacks/standin/server.py).

Drives the real `build_apps` output in-process against a fake upstream — no
Band, no harness, no Docker — so the proxy's contract (passthrough, SSE,
auth handling, header exclusion, control auth, script matching + cleanup,
bounded history) is pinned by fast deterministic tests, not the ~2-minute live
run. Marked `hermetic`, so it runs outside the suite's live E2E gate.
"""

from __future__ import annotations

import importlib.util
import json
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer

from driver.standin import Decision, Tool, call, decision

pytestmark = pytest.mark.hermetic

_SERVER_PATH = Path(__file__).resolve().parent.parent / "stacks" / "standin" / "server.py"
_spec = importlib.util.spec_from_file_location("standin_server", _SERVER_PATH)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

CONTROL_TOKEN = "probe-secret"
CTRL = {"X-Control-Token": CONTROL_TOKEN}
API_KEY = "real-key-from-env"
SEEN = web.AppKey("seen", list[dict])


def test_standin_settings_read_typed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stand-in's container settings expose its named configuration."""
    monkeypatch.setenv("STANDIN_CONTROL_TOKEN", CONTROL_TOKEN)
    monkeypatch.setenv("STANDIN_MODE", server.MODE_STRICT)
    monkeypatch.setenv("STANDIN_MODEL_PORT", "9080")

    settings = server.StandInSettings()

    assert settings.control_token == CONTROL_TOKEN
    assert settings.mode == server.MODE_STRICT
    assert settings.model_port == 9080


def test_standin_settings_reject_empty_control_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Compose default cannot start an unauthenticated control API."""
    monkeypatch.setenv("STANDIN_CONTROL_TOKEN", "")

    with pytest.raises(server.ValidationError, match="must be non-empty"):
        server.StandInSettings()


def test_tool_room_arg_does_not_fill_related_room_properties() -> None:
    tool = Tool(
        name="band_probe",
        schema={"properties": {"room_id": {}, "parent_room_id": {}}},
    )

    assert tool.room_arg("room-uuid") == {"room_id": "room-uuid"}


@dataclass
class Stack:
    model: TestClient  # the model-port app
    control: TestClient  # the control-port app
    upstream_seen: list[dict]  # requests the fake upstream received, in order
    standin: object  # the StandIn instance, for direct introspection

    async def install(
        self, token: str, *decisions: Decision, terminal: bool = False
    ) -> None:
        await install_script(self.control, token, *decisions, terminal=terminal)

    async def message(self, payload: dict) -> dict:
        response = await self.model.post("/v1/messages", json=payload)
        assert response.status == 200, await response.text()
        return await response.json()

    async def health(self) -> dict:
        response = await self.control.get("/control/healthz", headers=CTRL)
        assert response.status == 200
        return await response.json()

    async def calls(self, since: int = 0) -> list[dict]:
        response = await self.control.get(
            "/control/calls", params={"since": since}, headers=CTRL
        )
        assert response.status == 200
        return (await response.json())["calls"]


async def upstream_messages(request: web.Request) -> web.Response:
    request.app[SEEN].append(
        {
            "path": str(request.rel_url),
            "authorization": request.headers.get("Authorization"),
            "x-api-key": request.headers.get("x-api-key"),
            "telemetry": request.headers.get("x-stainless-lang"),
        }
    )
    return web.json_response(
        {"id": "msg_real", "content": [{"type": "text", "text": "real"}]}
    )


async def upstream_stream(request: web.Request) -> web.StreamResponse:
    request.app[SEEN].append({"path": str(request.rel_url)})
    response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
    await response.prepare(request)
    for chunk in (b"one\n", b"two\n", b"three\n"):
        await response.write(chunk)
    await response.write_eof()
    return response


async def upstream_ambient(request: web.Request) -> web.Response:
    request.app[SEEN].append({"path": str(request.rel_url)})
    return web.json_response({"ambient": True})


def upstream_app(seen: list[dict]) -> web.Application:
    app = web.Application()
    app[SEEN] = seen
    app.router.add_post("/v1/messages", upstream_messages)
    app.router.add_get("/stream-probe", upstream_stream)
    app.router.add_route("*", "/{tail:.*}", upstream_ambient)
    return app


@asynccontextmanager
async def running_stack(*, mode: str = server.MODE_PASSTHROUGH) -> AsyncIterator[Stack]:
    """Run the stand-in and, except in strict mode, its in-process upstream."""
    seen: list[dict] = []
    async with AsyncExitStack() as resources:
        upstream_url = "http://must-not-be-contacted"
        if mode != server.MODE_STRICT:
            upstream = TestServer(upstream_app(seen))
            await upstream.start_server()
            resources.push_async_callback(upstream.close)
            upstream_url = str(upstream.make_url("/")).rstrip("/")

        standin = server.StandIn(
            upstream=upstream_url,
            control_token=CONTROL_TOKEN,
            anthropic_api_key=API_KEY,
            mode=mode,
        )
        if mode != server.MODE_STRICT:
            standin.http = ClientSession(auto_decompress=False)
            resources.push_async_callback(standin.http.close)

        model_app, control_app = server.build_apps(standin)
        model = TestClient(TestServer(model_app))
        await model.start_server()
        resources.push_async_callback(model.close)
        control = TestClient(TestServer(control_app))
        await control.start_server()
        resources.push_async_callback(control.close)
        yield Stack(model=model, control=control, upstream_seen=seen, standin=standin)


@pytest.fixture
async def stack() -> AsyncIterator[Stack]:
    """A live stand-in wired to a fake upstream, both in-process."""
    async with running_stack() as value:
        yield value


def agent_turn(token: str, *, stream: bool = False) -> dict:
    """A tool-bearing model request whose latest user message carries `token`
    — the shape eligible for script matching."""
    return {
        "model": "claude-haiku-4-5",
        "stream": stream,
        "tools": [{"name": "band_send_message", "input_schema": {}}],
        "messages": [{"role": "user", "content": f"please handle {token} now"}],
    }


async def install_script(
    control: TestClient, token: str, *decisions: Decision, terminal: bool = False
) -> None:
    """Install neutral model decisions through the real control API."""
    response = await control.post(
        "/control/scripts",
        json={
            "token": token,
            "decisions": [item.payload() for item in decisions],
            "terminal": terminal,
        },
        headers=CTRL,
    )
    assert response.status == 201, await response.text()


def tool_result_turn(token: str, tool_use_id: str) -> dict:
    """The model follow-up a harness sends after executing one supplied tool."""
    turn = agent_turn(token)
    turn["messages"].append(
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": "ok"}
            ],
        }
    )
    return turn


# ---- control auth ---------------------------------------------------------


async def test_control_rejects_missing_token(stack: Stack):
    assert (await stack.control.get("/control/healthz")).status == 401


async def test_control_accepts_token(stack: Stack):
    response = await stack.control.get("/control/healthz", headers=CTRL)
    assert response.status == 200
    assert (await response.json())["status"] == "ok"


# ---- script validation ----------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"token": "T", "decisions": []}, id="empty-decisions"),
        pytest.param({"token": "T", "decisions": [{"nope": 1}]}, id="unknown-field"),
        pytest.param({"token": "T", "decisions": [{}]}, id="empty-decision"),
        pytest.param({"token": "", "decisions": [{"text": "x"}]}, id="blank-token"),
        pytest.param(
            {"token": "T", "decisions": [{"tool_calls": [{"name": "t", "args": {}}]}]},
            id="trailing-tool-call-not-terminal",
        ),
    ],
)
async def test_script_rejected_at_registration(stack: Stack, payload: dict):
    response = await stack.control.post("/control/scripts", json=payload, headers=CTRL)
    assert response.status == 400


async def test_trailing_tool_call_allowed_when_terminal(stack: Stack):
    response = await stack.control.post(
        "/control/scripts",
        json={
            "token": "T",
            "decisions": [{"tool_calls": [{"name": "t", "args": {}}]}],
            "terminal": True,
        },
        headers=CTRL,
    )
    assert response.status == 201


async def test_duplicate_token_conflicts(stack: Stack):
    body = {"token": "DUP", "decisions": [{"text": "hi"}]}
    assert (await stack.control.post("/control/scripts", json=body, headers=CTRL)).status == 201
    assert (await stack.control.post("/control/scripts", json=body, headers=CTRL)).status == 409


# ---- passthrough + auth ---------------------------------------------------


async def test_passthrough_replaces_placeholder_auth(stack: Stack):
    response = await stack.model.post(
        "/v1/messages?beta=true",
        json={"model": "m", "messages": [{"role": "user", "content": "hello"}]},
        headers={"Authorization": "Bearer placeholder", "x-stainless-lang": "js"},
    )
    body = await response.json()
    seen = stack.upstream_seen[-1]
    assert body["id"] == "msg_real"
    assert seen["x-api-key"] == API_KEY  # injected from env
    assert seen["authorization"] is None  # placeholder dropped, not both sent
    assert seen["telemetry"] is None  # SDK telemetry header stripped
    assert seen["path"] == "/v1/messages?beta=true"  # query preserved


async def test_passthrough_forwards_real_client_key(stack: Stack):
    await stack.model.post(
        "/v1/messages",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        headers={"x-api-key": "client-key"},
    )
    assert stack.upstream_seen[-1]["x-api-key"] == "client-key"  # not overwritten


async def test_ambient_route_forwarded_and_unrecorded(stack: Stack):
    response = await stack.model.get("/api/claude_code/settings")
    assert (await response.json())["ambient"] is True
    assert await stack.calls() == []  # only /v1/messages is recorded


async def test_streamed_upstream_relayed_intact(stack: Stack):
    """A chunked upstream response is relayed transparently — the proxy streams
    the bytes through rather than buffering, and preserves the content type."""
    response = await stack.model.get("/stream-probe")
    assert response.headers["Content-Type"] == "text/event-stream"
    assert await response.read() == b"one\ntwo\nthree\n"


async def test_unparseable_passthrough_request_is_recorded_as_forwarded(stack: Stack):
    response = await stack.model.post(
        "/v1/messages", data=b"[]", headers={"Content-Type": "application/json"}
    )

    assert response.status == 200
    assert stack.standin.calls[-1]["served"] == "passthrough"
    assert stack.standin.calls[-1]["upstream_status"] == 200


# ---- scripting ------------------------------------------------------------


async def test_scripted_tool_use_buffered(stack: Stack):
    token = "PA-BUF"
    await stack.install(
        token,
        decision(tool_calls=[call("band_send_message", {"text": "yo"})]),
        decision(text=f"Echo {token} done"),
    )
    message = await stack.message(agent_turn(token))
    block = message["content"][0]
    assert block["type"] == "tool_use" and message["stop_reason"] == "tool_use"
    assert token in block["id"]  # deterministic, token-bearing id


async def test_scripted_text_streamed_as_sse(stack: Stack):
    token = "PA-SSE"
    await stack.install(token, decision(text=f"Echo {token} done"))
    response = await stack.model.post("/v1/messages", json=agent_turn(token, stream=True))
    assert response.headers["Content-Type"].startswith("text/event-stream")
    sse = await response.text()
    assert f"Echo {token} done" in sse and "message_stop" in sse


async def test_exhausted_queue_passes_through_and_autoremoves(stack: Stack):
    token = "PA-EXH"
    await stack.install(token, decision(text="only once"))
    first = await stack.message(agent_turn(token))
    assert first["id"] == f"msg_standin_{token}"  # served scripted
    second = await stack.message(agent_turn(token))
    assert second["id"] == "msg_real"  # queue empty -> passthrough
    health = await stack.health()
    assert health["scripts"] == 0  # auto-removed on exhaustion


async def test_strict_mode_rejects_unmatched_model_request_without_egress():
    """Strict mode's failure is observable locally; it never needs an HTTP client."""
    async with running_stack(mode=server.MODE_STRICT) as stack:
        response = await stack.model.post("/v1/messages", json=agent_turn("PA-MISS"))
        body = await response.json()
        assert response.status == 502
        assert "no script" in body["error"]["message"]
        assert stack.standin.http is None
        assert stack.standin.calls[0]["served"] == "rejected"


async def test_strict_mode_completes_scripted_tool_loop_without_egress():
    """A tool decision and its tool-result follow-up are fully supplied."""
    token = "PA-STRICT-TOOL"
    async with running_stack(mode=server.MODE_STRICT) as stack:
        await stack.install(
            token,
            decision(tool_calls=[call("band_get_participants")]),
            decision(text="The tool result was received."),
        )
        first = await stack.message(agent_turn(token))
        assert first["stop_reason"] == "tool_use"
        follow_up = tool_result_turn(token, first["content"][0]["id"])
        second = await stack.message(follow_up)
        assert second["content"][0]["text"] == "The tool result was received."
        assert stack.standin.http is None
        assert [record["served"] for record in stack.standin.calls] == ["scripted", "scripted"]


async def test_strict_tool_loop_accepts_openclaw_compacted_tool_id():
    """A provider adapter may compact the token-bearing Anthropic tool ID."""
    token = "PA-STRICT-TOOL"
    async with running_stack(mode=server.MODE_STRICT) as stack:
        await stack.install(
            token,
            decision(tool_calls=[call("band_get_participants")]),
            decision(text="The tool result was received."),
        )
        first = await stack.message(agent_turn(token))
        compact_id = first["content"][0]["id"].replace("_", "").replace("-", "")
        second = await stack.message(tool_result_turn(token, compact_id))

        assert second["content"][0]["text"] == "The tool result was received."
        assert [record["served"] for record in stack.standin.calls] == ["scripted", "scripted"]


async def test_strict_mode_rejects_ambient_requests_without_egress():
    async with running_stack(mode=server.MODE_STRICT) as stack:
        response = await stack.model.get("/api/claude_code/settings")
        assert response.status == 502
        assert stack.standin.http is None


async def test_history_echo_does_not_retrigger(stack: Stack):
    """A token only in older context (not the latest user message) must not
    consume a decision."""
    token = "PA-HIST"
    await stack.control.post(
        "/control/scripts",
        json={"token": token, "decisions": [{"text": "SHOULD NOT SERVE"}]},
        headers=CTRL,
    )
    echo_turn = {
        "model": "m",
        "tools": [{"name": "t", "input_schema": {}}],
        "messages": [
            {"role": "user", "content": f"old turn {token}"},
            {"role": "assistant", "content": f"Echo {token}"},
            {"role": "user", "content": "a fresh unrelated turn"},
        ],
    }
    response = await (await stack.model.post("/v1/messages", json=echo_turn)).json()
    assert response["id"] == "msg_real"  # passed through, decision untouched


async def test_tool_less_request_never_matches(stack: Stack):
    """A utility call (no tools) that quotes the token — e.g. session-title
    generation embedding the transcript — passes through, never eating a
    queued decision."""
    token = "PA-UTIL"
    await stack.control.post(
        "/control/scripts",
        json={"token": token, "decisions": [{"text": "SHOULD NOT SERVE"}]},
        headers=CTRL,
    )
    utility = {"model": "m", "messages": [{"role": "user", "content": f"title for {token}"}]}
    response = await (await stack.model.post("/v1/messages", json=utility)).json()
    assert response["id"] == "msg_real"


async def test_longest_token_wins_on_overlap(stack: Stack):
    for token, text in (("OVL-ABC", "SHORT"), ("OVL-ABCD", "LONG")):
        await stack.control.post(
            "/control/scripts",
            json={"token": token, "decisions": [{"text": text}]},
            headers=CTRL,
        )
    response = await (await stack.model.post("/v1/messages", json=agent_turn("OVL-ABCD"))).json()
    assert response["content"][0]["text"] == "LONG"  # the more specific marker


async def test_delete_script_removes_queue(stack: Stack):
    token = "PA-DEL"
    await stack.control.post(
        "/control/scripts",
        json={"token": token, "decisions": [{"text": "a"}, {"text": "b"}]},
        headers=CTRL,
    )
    deleted = await stack.control.delete(f"/control/scripts/{token}", headers=CTRL)
    assert deleted.status == 200
    assert (await deleted.json())["remaining_decisions"] == 2
    assert (await stack.control.delete(f"/control/scripts/{token}", headers=CTRL)).status == 404


# ---- recording ------------------------------------------------------------


async def test_recording_schema_and_flags(stack: Stack):
    token = "PA-REC"
    await stack.control.post(
        "/control/scripts",
        json={"token": token, "decisions": [{"text": "one"}]},
        headers=CTRL,
    )
    await stack.model.post("/v1/messages", json=agent_turn(token))  # scripted
    await stack.model.post("/v1/messages", json=agent_turn(token, stream=True))  # passthrough (exhausted), streamed
    await stack.model.post("/v1/messages", json={"model": "m", "messages": []})  # passthrough, buffered

    calls = await stack.calls()
    assert [c["index"] for c in calls] == [0, 1, 2]  # absolute, contiguous
    assert [c["served"] for c in calls] == ["scripted", "passthrough", "passthrough"]
    assert [c["streamed"] for c in calls] == [False, True, False]
    # No request headers are ever ingested — not merely redacted.
    dumped = json.dumps(calls).lower()
    assert "authorization" not in dumped and "x-api-key" not in dumped
    assert all("headers" not in c for c in calls)


# ---- pure helpers (no I/O) ------------------------------------------------


def test_bounded_history_survives_eviction(monkeypatch):
    """Absolute indices survive the rolling window; `calls_since` reports what
    remains, keyed on the absolute index."""
    monkeypatch.setattr(server, "CALLS_WINDOW", 3)
    standin = server.StandIn(upstream="http://x", control_token="t", anthropic_api_key=None)
    for _ in range(5):
        standin.record({}, served="passthrough", raw_len=0)
    assert standin.recorded == 5
    assert [c["index"] for c in standin.calls] == [2, 3, 4]  # oldest two evicted
    assert [c["index"] for c in standin.calls_since(0)] == [2, 3, 4]  # clamped, not reset
    assert [c["index"] for c in standin.calls_since(3)] == [3, 4]


def test_field_cap_truncates_oversized(monkeypatch):
    monkeypatch.setattr(server, "FIELD_CAP", 100)
    assert server.capped("small") == "small"
    stub = server.capped("y" * 200)
    assert stub["truncated"] and stub["serialized_bytes"] > 100 and stub["head"]
