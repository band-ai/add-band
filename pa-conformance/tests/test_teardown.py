"""Hermetic teardown guarantees for dedicated F4 harnesses."""

from __future__ import annotations

import logging

import pytest

from conftest import _teardown_bootstrap

pytestmark = pytest.mark.hermetic


class CleanupHarness:
    def __init__(self, name: str, events: list[str], *, fails: bool = False) -> None:
        self.name = name
        self.events = events
        self.fails = fails

    def down(self) -> None:
        self.events.append(f"down:{self.name}")
        if self.fails:
            raise RuntimeError(f"down failed: {self.name}")


class CleanupResources:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def reap_agent(self, agent_id: str) -> None:
        self.events.append(f"reap:{agent_id}")
        if agent_id == "broken-agent":
            raise RuntimeError("reap failed")


async def test_bootstrap_teardown_attempts_every_resource_after_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    caplog.set_level(logging.CRITICAL, logger="conftest")
    await _teardown_bootstrap(
        [
            CleanupHarness("broken-stack", events, fails=True),
            CleanupHarness("healthy-stack", events),
        ],
        ["broken-agent", "healthy-agent"],
        CleanupResources(events),
    )

    assert set(events) == {
        "reap:broken-agent",
        "reap:healthy-agent",
        "down:broken-stack",
        "down:healthy-stack",
    }
