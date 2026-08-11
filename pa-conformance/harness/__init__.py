"""Harness runners: stand a personal-agent harness up headlessly, connected to
hosted Band, and tear it down. One module per harness, one shared contract.

The registry below is the single source of truth for which harnesses exist;
tests and CI parametrize off it (mirroring the SDK toolkit's adapter-registry
principle: never hand-list harnesses at a call site).
"""

from __future__ import annotations

import types

from harness.contract import (
    BandIdentity,
    Harness,
    HarnessContext,
    ModelWire,
    Profile,
    ReadyTimeout,
)
from harness.hermes import HermesHarness
from harness.nanoclaw import NanoClawHarness
from harness.openclaw import OpenClawHarness

_REGISTERED = (NanoClawHarness, OpenClawHarness, HermesHarness)
HARNESSES: dict[str, type[Harness]] = {cls.name: cls for cls in _REGISTERED}
# A duplicated name would silently drop a harness from the dict — and the
# registry-driven tests would then never exercise it.
assert len(HARNESSES) == len(_REGISTERED), "duplicate harness name in registry"
# A harness without declared conformance facts cannot collect: the
# requires_profile marker and the T1 rows read these fields per harness.
for _cls in _REGISTERED:
    assert isinstance(getattr(_cls, "profile", None), Profile), (
        f"{_cls.__name__} declares no Profile (harness/contract.py)"
    )

#: Harness-name references for marker call sites, generated from the registry
#: so there is exactly one source of harness names:
#: `@pytest.mark.known_gap(HARNESS.hermes, reason=...)`. A typo fails at import
#: (AttributeError), not at collection — mirroring PROFILE_FIELD.
HARNESS = types.SimpleNamespace(**{name: name for name in HARNESSES})

__all__ = [
    "HARNESS",
    "HARNESSES",
    "BandIdentity",
    "Harness",
    "HarnessContext",
    "HermesHarness",
    "ModelWire",
    "NanoClawHarness",
    "OpenClawHarness",
    "Profile",
    "ReadyTimeout",
]
