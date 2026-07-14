"""Driver client for the model stand-in (stacks/standin/server.py).

Tests express model behavior in the neutral decision DSL (INT-800):
``decision(text=…)`` / ``decision(tool_calls=[call("band_send_message",
{...})])`` — the stand-in owns the single Anthropic wire translation. A script
binds a FIFO of decisions to the run-scoped marker token the test plants in
its Band turn; the stand-in serves them only to model requests whose latest
user-role message carries that token, so shared harnesses with interleaving
turns stay collision-free. The recorded ``ModelCall`` is the Tier-1 read
point: the composed context and tool set exactly as the harness put them on
the model wire.

One client per harness, built at bring-up from the stack's dynamically
published control port; every request carries the per-run control token.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict


@dataclass(frozen=True)
class Decision:
    """One neutral model decision: what the "model" says and/or dispatches."""

    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def payload(self) -> dict:
        body: dict = {}
        if self.text is not None:
            body["text"] = self.text
        if self.tool_calls:
            body["tool_calls"] = [
                {"name": c.name, "args": c.args} for c in self.tool_calls
            ]
        return body


def decision(
    text: str | None = None, tool_calls: tuple[ToolCall, ...] | list[ToolCall] = ()
) -> Decision:
    return Decision(text=text, tool_calls=tuple(tool_calls))


def call(name: str, args: dict | None = None) -> ToolCall:
    return ToolCall(name=name, args=args or {})


@dataclass(frozen=True)
class Tool:
    """A tool as the harness declared it on the model wire."""

    name: str
    schema: dict

    def room_arg(self, room_id: str) -> dict:
        """Return this tool's one declared current-room argument, if any.

        The conformance dispatch probe only supplies an explicit target where
        the schema uses a conventional room identifier. Other room-like
        properties can describe a parent or source room and must be left to
        the tool's own defaults.
        """
        properties = self.schema.get("properties", {})
        for name in ("room_id", "chat_room_id"):
            if name in properties:
                return {name: room_id}
        return {}


@dataclass(frozen=True)
class ModelCall:
    """One recorded /v1/messages request — bounded and secret-free at the
    server (headers are never ingested; oversized fields arrive as flagged
    truncation stubs)."""

    index: int
    model: str | None
    system: object  # string or content-block list, as the harness sent it
    messages: list
    tools: tuple[Tool, ...]
    streamed: bool
    served: str  # "scripted" | "passthrough" | "rejected"
    upstream_status: int | None
    error: str | None

    @classmethod
    def from_record(cls, record: dict) -> ModelCall:
        raw_tools = record.get("tools")
        tools = tuple(
            Tool(name=t.get("name", ""), schema=t.get("input_schema") or {})
            for t in (raw_tools if isinstance(raw_tools, list) else [])
            if isinstance(t, dict)
        )
        return cls(
            index=record["index"],
            model=record.get("model"),
            system=record.get("system"),
            messages=record.get("messages") or [],
            tools=tools,
            streamed=bool(record.get("streamed")),
            served=record["served"],
            upstream_status=record.get("upstream_status"),
            error=record.get("error"),
        )

    @property
    def truncated(self) -> bool:
        """Whether the server size-capped any recorded field to a stub — in
        which case a `carries()` miss may be a false negative (the needle could
        sit past the retained head). Surfaced in await_call's failure message
        so an oversized turn is diagnosable, not silently wrong."""
        return any(
            isinstance(field, dict) and field.get("truncated")
            for field in (self.system, self.messages, self.tools)
        )

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]

    def duplicate_tool_names(self) -> set[str]:
        """Tool names offered more than once — a collision in the surface."""
        names = self.tool_names
        return {name for name in names if names.count(name) > 1}

    def tool_ending(self, suffix: str) -> Tool | None:
        """The offered tool whose name ends with `suffix`, harness namespace
        aside (e.g. "band_get_participants")."""
        return next((t for t in self.tools if t.name.endswith(suffix)), None)

    def tool_results(self) -> list[tuple[str, str]]:
        """(tool_use_id, flattened content) of every tool_result block in the
        latest user-role message — the dispatch observation: the harness's
        real loop executed a (scripted) tool_use and reported back."""
        for message in reversed(self.messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                if not isinstance(content, list):
                    return []
                return [
                    (block.get("tool_use_id", ""), _flatten(block.get("content")))
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "tool_result"
                ]
        return []

    def tool_result_names(self, who) -> bool:
        """Whether any tool_result in this call names `who` (by id or display
        name) — the dispatch proof that the executed Band tool returned this
        room's participant. `who` is any object with `id` and `name`."""
        return any(
            who.id in content or who.name in content
            for _, content in self.tool_results()
        )

    def attributes_to(self, who) -> bool:
        """Whether the composed context identifies `who` (by id or display
        name) — how harnesses attribute a turn's author differ. `who` is any
        object with `id` and `name` (Owner, ProvisionedAgent)."""
        return self.carries(who.id) or self.carries(who.name)

    def carries(self, needle: str) -> bool:
        """Whether the call carries `needle` anywhere — system, messages, or
        tool surface. The correlation predicate matching a Band turn (its
        marker token) to the model request it produced."""
        return needle in json.dumps(
            {"system": self.system, "messages": self.messages, "model": self.model},
            default=str,
        ) or any(needle in t.name for t in self.tools)


def _flatten(content: object) -> str:
    """Searchable text out of any Anthropic content shape: strings pass
    through; dicts contribute their text-ish fields; lists concatenate."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_flatten(item) for item in content)
    if isinstance(content, dict):
        return "\n".join(
            _flatten(content.get(key))
            for key in ("text", "content", "messages")
            if content.get(key) is not None
        )
    return str(content)


class StandInError(AssertionError):
    """The stand-in did not show the expected model traffic.

    An AssertionError on purpose: in a conformance run "the harness never put
    this turn on the model wire" is a verdict about the harness, not
    test-infrastructure noise.
    """


class ModelStandIn:
    """Control-API client for one harness's stand-in."""

    def __init__(self, *, port: int, control_token: str, deadline_s: float):
        self._base_url = f"http://127.0.0.1:{port}"
        self._headers = {"X-Control-Token": control_token}
        self._deadline_s = deadline_s

    def _client(self) -> httpx.AsyncClient:
        # Per-use clients: control traffic is sparse, and no held connection
        # means no session-scoped lifecycle to manage.
        return httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers, timeout=10.0
        )

    async def script(
        self, token: str, *decisions: Decision, terminal: bool = False
    ) -> None:
        """Queue `decisions` (FIFO, one per matched model request) for turns
        carrying `token`. Malformed scripts are rejected here, at script time
        — never silently at serve time. A script ending in a tool call must
        pass terminal=True, acknowledging its follow-up request will fall
        through to the live model."""
        async with self._client() as http:
            response = await http.post(
                "/control/scripts",
                json={
                    "token": token,
                    "decisions": [d.payload() for d in decisions],
                    "terminal": terminal,
                },
            )
        if response.status_code != 201:
            raise StandInError(
                f"stand-in rejected script for {token!r}: "
                f"{response.status_code} {response.text}"
            )

    async def unscript(self, token: str) -> None:
        """Remove a script and any decisions left in its queue, so retry
        padding a settled turn didn't consume can't be re-matched by a later
        turn that quotes the token. A missing script is fine (already served to
        exhaustion, which the server auto-removes)."""
        async with self._client() as http:
            await http.delete(f"/control/scripts/{token}")

    async def calls(
        self,
        *,
        carrying: str | None = None,
        since: int = 0,
        served: str | None = None,
        agent_loop: bool = False,
        tool_result: bool = False,
    ) -> list[ModelCall]:
        """Recorded ModelCalls from index `since`, optionally filtered.
        See `_filter` for the predicates."""
        async with self._client() as http:
            calls, _ = await self._page(http, since)
        return self._filter(calls, carrying, served, agent_loop, tool_result)

    @staticmethod
    def _filter(
        calls: list[ModelCall],
        carrying: str | None,
        served: str | None,
        agent_loop: bool,
        tool_result: bool,
    ) -> list[ModelCall]:
        """carrying: only calls whose payload carries the text (ModelCall.carries).
        served: "scripted"/"passthrough". agent_loop: only calls that offer
        tools — the agent-loop request, not a tool-less utility call (session
        titles) that can echo the same token. tool_result: only calls carrying
        a tool_result — the follow-up a dispatched tool produced (found by
        presence, since harnesses rewrite tool ids — OpenClaw strips `_`/`-`)."""
        if carrying is not None:
            calls = [c for c in calls if c.carries(carrying)]
        if served is not None:
            calls = [c for c in calls if c.served == served]
        if agent_loop:
            calls = [c for c in calls if c.tools]
        if tool_result:
            calls = [c for c in calls if c.tool_results()]
        return calls

    @staticmethod
    async def _page(
        http: httpx.AsyncClient, since: int
    ) -> tuple[list[ModelCall], int]:
        """The recorded calls at index >= `since`, plus the next cursor."""
        response = await http.get("/control/calls", params={"since": since})
        response.raise_for_status()
        payload = response.json()
        return [ModelCall.from_record(r) for r in payload["calls"]], int(payload["next"])

    async def await_call(
        self,
        *,
        carrying: str | None = None,
        since: int = 0,
        served: str | None = None,
        agent_loop: bool = False,
        tool_result: bool = False,
        deadline_s: float | None = None,
    ) -> ModelCall:
        """The first recorded model request matching the filters, waiting up to
        the deadline for the harness to make it. Each poll reads only records
        new since the last, so the wait cost is O(new calls). Raises
        StandInError (an assertion: the harness never put this turn on the model
        wire) with the traffic that WAS recorded — noting any size-capped call,
        whose truncation could hide the needle."""
        deadline = time.monotonic() + (deadline_s or self._deadline_s)
        seen: list[ModelCall] = []
        pos = since
        async with self._client() as http:
            while True:
                page, pos = await self._page(http, pos)
                seen.extend(page)
                found = self._filter(page, carrying, served, agent_loop, tool_result)
                if found:
                    return found[0]
                if time.monotonic() >= deadline:
                    capped = [c.index for c in seen if c.truncated]
                    note = f"; size-capped calls (may hide it): {capped}" if capped else ""
                    want = carrying if carrying is not None else (
                        "a tool_result" if tool_result else "any"
                    )
                    raise StandInError(
                        f"no {served or 'model'} call matching {want!r} "
                        f"recorded within {deadline_s or self._deadline_s:.0f}s "
                        f"(calls since {since}: "
                        f"{[(c.index, c.served) for c in seen]}){note}"
                    )
                await asyncio.sleep(1.0)

    async def cursor(self) -> int:
        """The current recording position, for scoping a later read to calls
        from here on — read from the healthz counter, no bodies fetched."""
        async with self._client() as http:
            response = await http.get("/control/healthz")
            response.raise_for_status()
            return int(response.json()["calls"])
