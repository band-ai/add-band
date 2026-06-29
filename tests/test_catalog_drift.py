"""Meta-tests: every integration folder participates in CI or is an explicit stub.

Mirrors ``tests/framework_conformance/test_config_drift.py`` in
thenvoi-sdk-python: if a new integration folder is added but neither given a
manifest (so ``check.py`` validates it) nor listed as a README-only stub, these
tests fail — surfacing the gap before an integration silently drops out of CI.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

import check


class TestCatalogDrift:
    """Every integration folder is either participating or an explicit stub."""

    def test_every_integration_is_classified(self):
        """No folder falls through: discovered == participating ∪ STUB_ONLY."""
        uncovered = check.integration_dirs() - check.participating_dirs() - check.STUB_ONLY
        assert not uncovered, (
            f"Integration folders neither participating nor stubbed: {sorted(uncovered)}. "
            f"Add a manifest.yaml + bootstrap.sh so check.py validates it, or add the "
            f"folder name to STUB_ONLY in scripts/check.py."
        )

    def test_no_stale_stubs(self):
        """STUB_ONLY names still exist on disk."""
        stale = check.STUB_ONLY - check.integration_dirs()
        assert not stale, (
            f"STUB_ONLY references folders that no longer exist: {sorted(stale)}. "
            f"Remove them from scripts/check.py."
        )

    def test_stubs_are_not_also_participating(self):
        """A folder is a stub xor a participating integration, never both."""
        contradictory = check.STUB_ONLY & check.participating_dirs()
        assert not contradictory, (
            f"STUB_ONLY folders that also have a manifest.yaml: {sorted(contradictory)}. "
            f"A folder is either a stub or a participating integration."
        )


class TestParticipatingIntegrations:
    """Each participating integration is well-formed and ships a valid snippet."""

    @pytest.mark.parametrize("name", sorted(check.participating_dirs()))
    def test_manifest_and_bootstrap_valid(self, name):
        problems = check.validate_integration(name)
        assert not problems, "\n".join(problems)

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    @pytest.mark.parametrize("name", sorted(check.participating_dirs()))
    def test_bootstrap_syntax(self, name):
        script = check.ROOT / name / "bootstrap.sh"
        result = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr


class TestSharedRegisterAgentHelper:
    """The shared registration helper stays syntactically valid and synced."""

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_canonical_helper_syntax(self):
        script = check.ROOT / "scripts" / "register-agent.sh"
        result = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skip(
        reason="check-register-agent-sync taken out of play while the agent-key "
        "var name (BAND_AGENT_API_KEY) is reconciled across the catalog and fork"
    )
    def test_existing_helper_copies_do_not_drift(self):
        script = check.ROOT / "scripts" / "check-register-agent-sync.py"
        result = subprocess.run(
            ["python3", str(script)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
