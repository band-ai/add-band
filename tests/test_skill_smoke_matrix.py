"""bootstrap-skill-smoke.yml's skill matrix and case arms track STUB_ONLY.

The workflow's `compute-matrix` job derives `matrix.skill` from
`check.STUB_ONLY` at run time rather than a second, hand-spelled list, and its
per-skill `case "${{ matrix.skill }}"` blocks fail loudly on an unmatched
skill — but neither of those live-only mechanisms is exercised by a normal
`pytest tests/ -q` run. These tests catch a mistake in either without needing
a credentialed GitHub Actions run.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap

import check

WORKFLOW = check.ROOT / ".github/workflows/bootstrap-skill-smoke.yml"


def _compute_matrix_script() -> str:
    """The literal Python heredoc the `compute-matrix` job's `skills` step runs."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"python3 - <<'PY'[^\n]*\n(.*?)\n\s*PY\b", text, re.DOTALL)
    assert match, "compute-matrix's python heredoc not found in bootstrap-skill-smoke.yml"
    return textwrap.dedent(match.group(1))


def _skill_case_arms() -> list[set[str]]:
    """Arm labels (excluding `*)`) of every `case "${{ matrix.skill }}"` block."""
    text = WORKFLOW.read_text(encoding="utf-8")
    blocks = re.findall(r'case "\$\{\{ matrix\.skill \}\}" in(.*?)\besac\b', text, re.DOTALL)
    return [set(re.findall(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\)", block, re.MULTILINE)) for block in blocks]


def _install_cli_arm_bodies() -> dict[str, str]:
    """Label -> script body for each arm of the `Install CLI` step's case block."""
    text = WORKFLOW.read_text(encoding="utf-8")
    step = re.search(r"name: Install CLI\n\s*run: \|\n(.*?)\n(?=\s*- name:)", text, re.DOTALL)
    assert step, "Install CLI step not found in bootstrap-skill-smoke.yml"
    arms = re.findall(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\)\n(.*?)\n\s*;;", step.group(1), re.DOTALL | re.MULTILINE)
    return dict(arms)


def _setup_node_allowlist() -> set[str]:
    """The skill set `setup-node`'s `if: contains(fromJson(...), matrix.skill)` allowlists."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"if: contains\(fromJson\('(\[.*?\])'\), matrix\.skill\)", text)
    assert match, "setup-node's allowlist if: not found in bootstrap-skill-smoke.yml"
    return set(json.loads(match.group(1)))


class TestComputeMatrix:
    """The compute-matrix job's own logic, run exactly as committed."""

    def test_emits_stub_only(self):
        result = subprocess.run(
            [sys.executable, "-c", _compute_matrix_script()],
            cwd=check.ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        output = result.stdout.strip()
        assert output.startswith("skills="), output
        assert json.loads(output.removeprefix("skills=")) == sorted(check.STUB_ONLY)


class TestSkillCaseArms:
    """Every `case "${{ matrix.skill }}"` block covers exactly STUB_ONLY."""

    def test_every_case_block_covers_stub_only(self):
        arm_sets = _skill_case_arms()
        assert arm_sets, 'no case "${{ matrix.skill }}" blocks found in bootstrap-skill-smoke.yml'
        for arms in arm_sets:
            assert arms == check.STUB_ONLY, (
                f"case arms {sorted(arms)} != STUB_ONLY {sorted(check.STUB_ONLY)} "
                f"in one of bootstrap-skill-smoke.yml's case blocks."
            )


class TestSetupNodeAllowlist:
    """`setup-node`'s skill allowlist covers exactly the skills whose Install CLI arm needs npm."""

    def test_matches_npm_installing_skills(self):
        npm_skills = {
            label for label, body in _install_cli_arm_bodies().items() if "npm install" in body
        }
        assert npm_skills, "no Install CLI arm invokes npm install"
        allowlist = _setup_node_allowlist()
        assert allowlist == npm_skills, (
            f"setup-node's allowlist {sorted(allowlist)} != skills whose Install CLI arm "
            f"invokes npm install {sorted(npm_skills)}"
        )
