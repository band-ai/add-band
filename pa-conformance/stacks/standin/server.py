"""The model stand-in: an always-on recording proxy in each stack's model path.

Each harness routes its model calls here (via ANTHROPIC_BASE_URL, or a
provider-config knob where the SDK ignores that env var). `passthrough` mode
records every /v1/messages request and forwards unmatched calls to Anthropic.
`strict` mode serves registered scripts only: unmatched model and ambient
requests fail locally, and no HTTP client is created. A script binds a FIFO of
neutral decisions ({text?, tool_calls?}) to a run-scoped token; a tool-bearing
model request whose LATEST user-role message carries that token consumes the
next decision. History echoes never re-trigger a script. A multi-decision
script supplies the post-tool response too, so deterministic integration
coverage never depends on a live model.

Two listeners, one process:
  - the model port serves /v1/messages (scripted-or-passthrough). In
    passthrough mode it forwards ambient Claude-family routes too; strict mode
    rejects them so an unexpected dependency is explicit.
  - the control port serves the driver (scripts, recorded calls, healthz);
    every control request must carry X-Control-Token (the per-run secret) —
    both ports are reachable from the harness network, so isolation by port
    would be fiction.

Recorded ModelCalls are bounded and secret-free: request headers are dropped
at ingest (never merely redacted later), each field is size-capped with the
truncation flagged. Records live in memory and die with the container.

The stand-in's own egress deliberately ignores HTTPS_PROXY/NO_PROXY (aiohttp
default, trust_env=False): those govern harness containers, not this proxy.

Env:
  STANDIN_CONTROL_TOKEN      required — the per-run control-API secret
  STANDIN_UPSTREAM           default https://api.anthropic.com (overridable
                             only for the stand-in's own tests)
  STANDIN_ANTHROPIC_API_KEY  optional — replaces absent/placeholder client
                             auth on forward, for harnesses whose runtimes
                             never hold the real key (NanoClaw siblings carry
                             ANTHROPIC_AUTH_TOKEN=placeholder; the vault MITM
                             that would inject the real key only intercepts
                             https egress, and the stand-in is plain http)
  STANDIN_MODE               passthrough (default) or strict
  STANDIN_MODEL_PORT / STANDIN_CONTROL_PORT   defaults 8080 / 8081
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from collections import deque

from aiohttp import ClientError, ClientSession, ClientTimeout, web
from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Per-field cap on recorded values (serialized bytes); truncation flagged.
#: Comfortably above any realistic conformance turn (system prompt + tool
#: schemas + transcript), so it is a pathological-only safety valve rather
#: than something that trims a normal turn's observable context.
FIELD_CAP = 1_000_000

#: Most-recent recorded calls kept in memory. Bounded so a long session (many
#: multi-inference agent loops) can't grow the recording without limit; far
#: above any single test's read window, and absolute `since` indices survive
#: eviction (handle_get_calls reports `next` as the total ever recorded).
CALLS_WINDOW = 4096

#: Request headers forwarded upstream. Everything else — hop-by-hop headers,
#: SDK telemetry — is dropped; Host is rewritten by the client.
FORWARDED_HEADERS = ("content-type", "accept", "authorization", "x-api-key", "user-agent")
FORWARDED_HEADER_PREFIXES = ("anthropic-",)

#: Hop-by-hop response headers never copied back (content-length re-derives
#: from the chunked stream).
DROPPED_RESPONSE_HEADERS = frozenset(
    {"connection", "keep-alive", "transfer-encoding", "upgrade", "content-length"}
)

#: Fixed synthetic usage for scripted responses.
SCRIPTED_USAGE = {
    "input_tokens": 1,
    "output_tokens": 1,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}

MODE_STRICT = "strict"
MODE_PASSTHROUGH = "passthrough"
MODES = frozenset((MODE_STRICT, MODE_PASSTHROUGH))


class StandInSettings(BaseSettings):
    """Environment-backed configuration for one stand-in container.

    Every field uses the ``STANDIN_`` prefix, keeping the model proxy's
    configuration separate from the PA harness and its credentials.
    """

    model_config = SettingsConfigDict(env_prefix="STANDIN_", extra="ignore")

    #: Per-run secret required by every control-API request.
    control_token: str
    #: Upstream used only by passthrough mode and stand-in tests.
    upstream: str = "https://api.anthropic.com"
    #: Optional replacement for absent or placeholder harness credentials.
    anthropic_api_key: str | None = None
    #: Whether requests are forwarded or served from registered scripts.
    mode: str = MODE_PASSTHROUGH
    #: Listener ports inside the stand-in container.
    model_port: int = 8080
    control_port: int = 8081

    @field_validator("control_token")
    @classmethod
    def control_token_is_nonempty(cls, value: str) -> str:
        """Reject an empty Compose interpolation before serving control routes."""
        if not value.strip():
            raise ValueError("must be non-empty")
        return value


class ScriptError(ValueError):
    """A malformed script, rejected at script time (400) — never at serve."""


def parse_script(payload: object) -> tuple[str, list[dict]]:
    """Validate a control-API script payload; return (token, decisions).

    `terminal` is accepted (and must be bool) purely to permit a trailing
    tool-call decision: a tool_use turn always provokes a follow-up model
    request, and an exhausted queue there would silently fall through to the
    live model — so a script ending in a tool call must acknowledge that with
    terminal=True. The flag has no serve-time effect, so it is not stored."""
    if not isinstance(payload, dict) or set(payload) - {"token", "decisions", "terminal"}:
        raise ScriptError("script takes exactly: token, decisions, terminal?")
    token = payload.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ScriptError("token must be a non-empty string")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ScriptError("decisions must be a non-empty list")
    for decision in decisions:
        parse_decision(decision)
    terminal = payload.get("terminal", False)
    if not isinstance(terminal, bool):
        raise ScriptError("terminal must be a bool")
    if decisions[-1].get("tool_calls") and not terminal:
        raise ScriptError(
            "the last decision is a tool call — a tool_use turn always "
            "provokes a follow-up model request, and an exhausted queue there "
            "would silently fall through to the live model; append a text "
            "decision for the follow-up or mark the script terminal"
        )
    return token, decisions


def parse_decision(decision: object) -> None:
    """One neutral model decision: {text?, tool_calls?}, at least one of them,
    nothing else (the INT-800 DSL)."""
    if not isinstance(decision, dict) or set(decision) - {"text", "tool_calls"}:
        raise ScriptError("a decision takes only text and/or tool_calls")
    text, tool_calls = decision.get("text"), decision.get("tool_calls")
    if text is None and not tool_calls:
        raise ScriptError("a decision needs text or tool_calls")
    if text is not None and (not isinstance(text, str) or not text):
        raise ScriptError("decision text must be a non-empty string")
    if tool_calls is not None:
        if not isinstance(tool_calls, list) or not tool_calls:
            raise ScriptError("tool_calls must be a non-empty list")
        for call in tool_calls:
            if (
                not isinstance(call, dict)
                or set(call) != {"name", "args"}
                or not isinstance(call["name"], str)
                or not call["name"]
                or not isinstance(call["args"], dict)
            ):
                raise ScriptError("a tool call is {name: str, args: object}")


def wire_message(decision: dict, *, token: str, model: str, tool_id_base: int) -> dict:
    """The single Anthropic wire translation of a neutral decision.

    tool_use ids are deterministic and token-bearing on purpose: they keep the
    recorded ModelCalls reproducible and secret-free, and a harness echoes the
    id back inside its tool_result so the token surfaces in a follow-up
    request's payload. Follow-up matching accepts OpenClaw's compacted form
    too (it strips `_`/`-`)."""
    blocks: list[dict] = []
    if text := decision.get("text"):
        blocks.append({"type": "text", "text": text})
    for n, call in enumerate(decision.get("tool_calls") or [], start=tool_id_base):
        blocks.append(
            {
                "type": "tool_use",
                "id": f"toolu_standin_{token}_{n}",
                "name": call["name"],
                "input": call["args"],
            }
        )
    return {
        "id": f"msg_standin_{token}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": blocks,
        "stop_reason": "tool_use" if decision.get("tool_calls") else "end_turn",
        "stop_sequence": None,
        "usage": SCRIPTED_USAGE,
    }


def sse_events(message: dict):
    """Render a complete message as the Anthropic streaming event sequence."""
    yield "message_start", {
        "type": "message_start",
        "message": {**message, "content": [], "stop_reason": None},
    }
    for index, block in enumerate(message["content"]):
        if block["type"] == "text":
            start = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": block["text"]}
        else:
            start = {**block, "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        yield "content_block_start", {
            "type": "content_block_start", "index": index, "content_block": start,
        }
        yield "content_block_delta", {
            "type": "content_block_delta", "index": index, "delta": delta,
        }
        yield "content_block_stop", {"type": "content_block_stop", "index": index}
    yield "message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
        "usage": {"output_tokens": 1},
    }
    yield "message_stop", {"type": "message_stop"}


def capped(value: object) -> object:
    """The value, or a flagged truncation stub when it exceeds FIELD_CAP."""
    text = json.dumps(value, default=str)
    if len(text) <= FIELD_CAP:
        return value
    return {"truncated": True, "serialized_bytes": len(text), "head": text[:2000]}


def latest_user_message(body: dict) -> object | None:
    for message in reversed(body.get("messages") or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return message
    return None


def delivery_token_variants(token: str) -> tuple[str, ...]:
    """Token spellings retained by harness tool-result ID adapters.

    OpenClaw removes underscores and hyphens from Anthropic tool-use IDs. The
    compact spelling is matched only against active, run-scoped scripts, so it
    restores a follow-up decision without searching older conversation turns.
    """
    compact = token.replace("_", "").replace("-", "")
    return (token,) if compact == token else (token, compact)


class StandIn:
    def __init__(
        self,
        *,
        upstream: str,
        control_token: str,
        anthropic_api_key: str | None,
        mode: str = MODE_PASSTHROUGH,
    ):
        if mode not in MODES:
            raise ValueError(
                f"unknown stand-in mode {mode!r}; expected one of {sorted(MODES)}"
            )
        self.upstream = upstream.rstrip("/")
        self.control_token = control_token
        self.anthropic_api_key = anthropic_api_key
        self.mode = mode
        #: A bounded rolling window of the most recent records; `recorded` is
        #: the total ever appended, so absolute indices survive eviction.
        self.calls: deque[dict] = deque(maxlen=CALLS_WINDOW)
        self.recorded = 0
        #: token -> {"queue": deque[decision], "tool_ids": int}. Invariant: a
        #: registered script always holds a non-empty queue — registration
        #: rejects an empty one, and serve_scripted removes the script the
        #: moment its queue empties.
        self.scripts: dict[str, dict] = {}
        self.http: ClientSession | None = None

    # ---- model port -------------------------------------------------------

    async def handle_messages(self, request: web.Request) -> web.StreamResponse:
        """Serve a matching script, or follow this instance's model policy."""
        raw = await request.read()
        try:
            body = json.loads(raw)
            assert isinstance(body, dict)
        except (ValueError, AssertionError):
            record = self.record(
                {},
                served="rejected" if self.mode == MODE_STRICT else "passthrough",
                raw_len=len(raw),
            )
            record["error"] = "unparseable request body"
            if self.mode == MODE_STRICT:
                return self.rejected("strict mode rejects an unparseable model request")
            return await self.forward(request, raw, record)

        token = self.matching_token(body)
        if token is not None:
            # matching_token only returns a registered token, and a registered
            # script always holds a non-empty queue (see self.scripts), so the
            # serve consumes a decision without a further guard.
            return await self.serve_scripted(
                request, body, token, self.scripts[token], len(raw)
            )
        record = self.record(body, served="passthrough", raw_len=len(raw))
        if self.mode == MODE_STRICT:
            record["served"] = "rejected"
            record["error"] = "strict mode has no script for this model request"
            return self.rejected(record["error"])
        return await self.forward(request, raw, record)

    def matching_token(self, body: dict) -> str | None:
        """The registered token carried by the request's LATEST user-role
        message — matched against the whole message (text blocks and
        tool_result payloads, where the token-bearing tool_use id echoes
        back), never against older context. OpenClaw's compacted tool-use ID
        spelling is accepted for the active script too.

        Only requests that OFFER TOOLS are eligible: a scripted decision is
        an agent-loop decision, and harness utility calls (observed live:
        NanoClaw's session-title generation embeds the turn transcript, so
        it carries the token) declare no tools — they pass through to the
        live model instead of silently eating a queued decision.

        When several registered tokens are carried (one a substring of
        another, e.g. `abc` and `abcd`), the LONGEST wins — the most specific
        marker — so prefix overlap routes deterministically."""
        if not body.get("tools"):
            return None
        latest = latest_user_message(body)
        if latest is None:
            return None
        haystack = json.dumps(latest)
        matches = [
            token
            for token in self.scripts
            if any(variant in haystack for variant in delivery_token_variants(token))
        ]
        return max(matches, key=len) if matches else None

    async def serve_scripted(
        self, request: web.Request, body: dict, token: str, script: dict, raw_len: int
    ) -> web.StreamResponse:
        decision = script["queue"].popleft()
        message = wire_message(
            decision,
            token=token,
            model=body.get("model", "unknown"),
            tool_id_base=script["tool_ids"],
        )
        script["tool_ids"] += len(decision.get("tool_calls") or [])
        # Drop the script once its queue empties: a consumed script must not
        # linger to be re-matched by a later turn that quotes its token, nor
        # accumulate across a session's scripted turns.
        if not script["queue"]:
            self.scripts.pop(token, None)
        self.record(body, served="scripted", raw_len=raw_len)
        if not body.get("stream"):
            return web.json_response(message)
        response = web.StreamResponse(
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
        )
        await response.prepare(request)
        for event, data in sse_events(message):
            await response.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
        await response.write_eof()
        return response

    async def handle_ambient(self, request: web.Request) -> web.StreamResponse:
        """Everything that is not the seam — settings, policy, telemetry,
        registry — forwards transparently and is not recorded."""
        if self.mode == MODE_STRICT:
            return self.rejected(
                f"strict mode rejects ambient request {request.method} {request.rel_url}"
            )
        return await self.forward(request, await request.read(), record=None)

    @staticmethod
    def rejected(message: str) -> web.Response:
        """A deterministic Anthropic-shaped failure with no upstream request."""
        return web.json_response(
            {
                "type": "error",
                "error": {"type": "api_error", "message": f"stand-in: {message}"},
            },
            status=502,
        )

    async def forward(
        self, request: web.Request, raw_body: bytes, record: dict | None
    ) -> web.StreamResponse:
        assert self.http is not None, "passthrough mode requires an HTTP client"
        headers = self.forwarded_request_headers(request)
        response: web.StreamResponse | None = None
        try:
            async with self.http.request(
                request.method,
                self.upstream + str(request.rel_url),
                headers=headers,
                data=raw_body,
            ) as upstream:
                if record is not None:
                    record["upstream_status"] = upstream.status
                response = web.StreamResponse(
                    status=upstream.status,
                    headers={
                        name: value
                        for name, value in upstream.headers.items()
                        if name.lower() not in DROPPED_RESPONSE_HEADERS
                    },
                )
                await response.prepare(request)
                async for chunk in upstream.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
                return response
        except (ClientError, asyncio.TimeoutError, OSError) as exc:
            # Once the response is prepared the status/headers are already on
            # the wire, so a 502 is impossible — end the (truncated) stream so
            # the client sees EOF instead of a hang, and record the break.
            if response is not None and response.prepared:
                if record is not None:
                    record["error"] = f"upstream stream interrupted: {exc!r}"
                with contextlib.suppress(Exception):
                    await response.write_eof()
                return response
            detail = f"upstream connection failed: {exc!r}"
            if record is not None:
                record["error"] = detail
            return web.json_response(
                {"type": "error", "error": {"type": "api_error", "message": f"stand-in: {detail}"}},
                status=502,
            )

    def forwarded_request_headers(self, request: web.Request) -> dict[str, str]:
        # request.headers is a case-insensitive CIMultiDict; the forward dict
        # preserves the client's original casing.
        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() in FORWARDED_HEADERS
            or name.lower().startswith(FORWARDED_HEADER_PREFIXES)
        }
        if self.anthropic_api_key and not self.real_client_auth(request.headers):
            # Drop every casing of Authorization before injecting the real key.
            for name in [n for n in headers if n.lower() == "authorization"]:
                del headers[name]
            headers["x-api-key"] = self.anthropic_api_key
        return headers

    @staticmethod
    def real_client_auth(headers) -> bool:
        """Whether the client sent a credential worth forwarding. NanoClaw
        siblings authenticate with the literal ANTHROPIC_AUTH_TOKEN
        `placeholder` (the real key normally joins via the vault's https
        MITM, which never sees plain-http egress to the stand-in). `headers`
        is the request's case-insensitive multidict."""
        if headers.get("x-api-key", "").strip():
            return True
        auth = headers.get("authorization", "").strip()
        bearer = auth[7:].strip() if auth[:7].lower() == "bearer " else auth
        return bearer not in ("", "placeholder")

    def record(self, body: dict, *, served: str, raw_len: int) -> dict:
        """Append a bounded, secret-free ModelCall (headers are never
        ingested). Appended before the upstream round-trip so an in-flight or
        hung call is already observable; status/error land as they resolve.

        The per-field size cap only serializes when the whole request exceeds
        FIELD_CAP — a request smaller than the cap has no field larger than it,
        so the common case skips three json.dumps in the proxy hot path."""
        cap = capped if raw_len > FIELD_CAP else (lambda value: value)
        record = {
            "index": self.recorded,
            "model": body.get("model"),
            "system": cap(body.get("system")),
            "messages": cap(body.get("messages")),
            "tools": cap(body.get("tools")),
            "streamed": bool(body.get("stream")),
            "served": served,
            "upstream_status": None,
            "error": None,
        }
        self.recorded += 1
        self.calls.append(record)  # deque evicts the oldest past CALLS_WINDOW
        return record

    def calls_since(self, since: int) -> list[dict]:
        """Recorded calls with absolute index >= `since` still in the window.
        `since` is absolute and survives eviction: the window's first record
        has index `recorded - len(calls)`."""
        base = self.recorded - len(self.calls)
        return [record for record in self.calls if record["index"] >= since] if since > base else list(self.calls)

    # ---- control port -----------------------------------------------------

    @web.middleware
    async def control_auth(self, request: web.Request, handler):
        supplied = request.headers.get("X-Control-Token", "")
        if not hmac.compare_digest(supplied, self.control_token):
            return web.json_response({"error": "missing or bad X-Control-Token"}, status=401)
        return await handler(request)

    async def handle_healthz(self, request: web.Request) -> web.Response:
        # `calls` is the total ever recorded (the next absolute index), which
        # the driver reads as its `since` cursor without fetching any bodies.
        return web.json_response(
            {"status": "ok", "scripts": len(self.scripts), "calls": self.recorded}
        )

    async def handle_put_script(self, request: web.Request) -> web.Response:
        try:
            token, decisions = parse_script(await request.json())
        except ScriptError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except ValueError:
            return web.json_response({"error": "body must be JSON"}, status=400)
        if token in self.scripts:
            return web.json_response(
                {"error": f"a script for this token exists (queued: {len(self.scripts[token]['queue'])}); delete it first"},
                status=409,
            )
        self.scripts[token] = {"queue": deque(decisions), "tool_ids": 0}
        return web.json_response({"token": token, "queued": len(decisions)}, status=201)

    async def handle_delete_script(self, request: web.Request) -> web.Response:
        removed = self.scripts.pop(request.match_info["token"], None)
        if removed is None:
            return web.json_response({"error": "no such script"}, status=404)
        return web.json_response({"remaining_decisions": len(removed["queue"])})

    async def handle_get_calls(self, request: web.Request) -> web.Response:
        try:
            since = int(request.query.get("since", "0"))
        except ValueError:
            return web.json_response({"error": "since must be an integer"}, status=400)
        return web.json_response(
            {"calls": self.calls_since(since), "next": self.recorded}
        )


def build_apps(standin: StandIn) -> tuple[web.Application, web.Application]:
    """The (model, control) aiohttp apps wired to `standin`. The single source
    of routing for both main() and the server's own tests."""
    model = web.Application(client_max_size=64 * 1024**2)
    model.router.add_post("/v1/messages", standin.handle_messages)
    model.router.add_route("*", "/{tail:.*}", standin.handle_ambient)

    control = web.Application(middlewares=[standin.control_auth])
    control.router.add_get("/control/healthz", standin.handle_healthz)
    control.router.add_post("/control/scripts", standin.handle_put_script)
    control.router.add_delete("/control/scripts/{token}", standin.handle_delete_script)
    control.router.add_get("/control/calls", standin.handle_get_calls)
    return model, control


async def main() -> None:
    try:
        settings = StandInSettings()
    except ValidationError:
        # Compose interpolation defaults the variable to "" for teardown-only
        # invocations; an actually-started stand-in must never accept that.
        raise SystemExit("STANDIN_CONTROL_TOKEN must be set and non-empty")
    standin = StandIn(
        upstream=settings.upstream,
        control_token=settings.control_token,
        anthropic_api_key=settings.anthropic_api_key,
        mode=settings.mode,
    )
    if standin.mode == MODE_PASSTHROUGH:
        # No total timeout: passthrough streams legitimately run for minutes.
        standin.http = ClientSession(
            timeout=ClientTimeout(total=None, sock_connect=30), auto_decompress=False
        )

    model, control = build_apps(standin)
    for app, port in (
        (model, settings.model_port),
        (control, settings.control_port),
    ):
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
    print("stand-in serving", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
