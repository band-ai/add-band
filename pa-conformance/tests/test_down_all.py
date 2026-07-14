"""Failure handling for the compose-project teardown backstop."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.hermetic


def test_down_all_fails_when_compose_project_listing_fails(tmp_path: Path) -> None:
    docker = tmp_path / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 23\n")
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    script = Path(__file__).parents[1] / "stacks" / "down-all.sh"

    result = subprocess.run(
        ["bash", str(script)],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "failed to list PA-conformance compose projects" in result.stderr
