"""Harness runners: stand a personal-agent harness up headlessly, connected to
hosted Band, and tear it down. One module per harness, one shared contract.

The registry below is the single source of truth for which harnesses exist;
tests and CI parametrize off it (mirroring the SDK toolkit's adapter-registry
principle: never hand-list harnesses at a call site).
"""

from __future__ import annotations

from harness.contract import BandIdentity, Harness, HarnessContext, ReadyTimeout
from harness.hermes import HermesHarness
from harness.nanoclaw import NanoClawHarness
from harness.openclaw import OpenClawHarness

HARNESSES: dict[str, type[Harness]] = {
    cls.name: cls for cls in (NanoClawHarness, OpenClawHarness, HermesHarness)
}

__all__ = [
    "HARNESSES",
    "BandIdentity",
    "Harness",
    "HarnessContext",
    "HermesHarness",
    "NanoClawHarness",
    "OpenClawHarness",
    "ReadyTimeout",
]
