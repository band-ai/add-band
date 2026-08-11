"""ModelCall.from_record surfaces server-side truncation stubs.

An oversized field arrives from the stand-in as a flagged stub, not the raw
value; the driver must keep `truncated` true for it so a `carries()` miss on a
size-capped turn reads as diagnosable rather than a silent tool-less call.
"""

from __future__ import annotations

import pytest

from driver.standin import ModelCall

pytestmark = pytest.mark.hermetic


def _record(**overrides: object) -> dict:
    base: dict = {
        "index": 0,
        "system": "sys",
        "messages": [],
        "tools": [],
        "served": "passthrough",
    }
    base.update(overrides)
    return base


def test_truncated_flags_oversized_tools_stub() -> None:
    call = ModelCall.from_record(
        _record(tools={"truncated": True, "serialized_bytes": 2_000_000, "head": "[]"})
    )
    assert call.tools == ()
    assert call.tool_names == []
    assert call.truncated


def test_normal_tools_are_not_truncated() -> None:
    call = ModelCall.from_record(
        _record(tools=[{"name": "band_get_participants", "input_schema": {}}])
    )
    assert call.tool_names == ["band_get_participants"]
    assert not call.truncated


def test_truncated_flags_oversized_system_stub() -> None:
    call = ModelCall.from_record(_record(system={"truncated": True, "head": "x"}))
    assert call.truncated
