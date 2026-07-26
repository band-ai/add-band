"""Hermetic tests for the shared register-agent helper synchronization."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def sync_checker():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check-register-agent-sync.py"
    spec = importlib.util.spec_from_file_location("check_register_agent_sync", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _target(sync_checker, tmp_path: Path):
    repo = tmp_path / "integration"
    return sync_checker.Target("integration", repo, Path("skill/register-agent.sh"))


def test_matching_copy_is_accepted(sync_checker, tmp_path):
    canonical = tmp_path / "canonical.sh"
    canonical.write_text("canonical\n")
    copy = _target(sync_checker, tmp_path)
    copy.full_path.parent.mkdir(parents=True)
    copy.full_path.write_bytes(canonical.read_bytes())

    problems, messages = sync_checker.check_targets(canonical, [copy], strict=True)

    assert problems == []
    assert messages == ["integration: in sync"]


def test_drift_is_rejected(sync_checker, tmp_path):
    canonical = tmp_path / "canonical.sh"
    canonical.write_text("canonical\n")
    copy = _target(sync_checker, tmp_path)
    copy.full_path.parent.mkdir(parents=True)
    copy.full_path.write_text("drifted\n")

    problems, messages = sync_checker.check_targets(canonical, [copy], strict=False)

    assert messages == []
    assert problems == [f"integration: {copy.full_path} differs from {canonical}"]


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("missing", ["repo", "copy"])
def test_missing_target_respects_strict_mode(sync_checker, tmp_path, strict, missing):
    canonical = tmp_path / "canonical.sh"
    canonical.write_text("canonical\n")
    copy = _target(sync_checker, tmp_path)
    if missing == "copy":
        copy.repo.mkdir()
        expected = "integration: missing skill/register-agent.sh"
    else:
        expected = f"integration: repo not found at {copy.repo}"

    problems, messages = sync_checker.check_targets(canonical, [copy], strict=strict)

    assert problems == ([expected] if strict else [])
    assert messages == ([] if strict else [expected])


def test_sync_creates_an_exact_copy(sync_checker, tmp_path):
    canonical = tmp_path / "canonical.sh"
    canonical.write_text("canonical\n")
    canonical.chmod(0o751)
    copy = _target(sync_checker, tmp_path)
    copy.repo.mkdir()

    messages = sync_checker.sync_targets(canonical, [copy])

    assert messages == [f"synced integration: {copy.full_path}"]
    assert copy.full_path.read_bytes() == canonical.read_bytes()
    assert copy.full_path.stat().st_mode == canonical.stat().st_mode
