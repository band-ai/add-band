"""Acquire a band-sdk-python checkout for the baseline toolkit.

The toolkit is not shipped in the band-sdk wheel; it lives in the repo's tests
tree, so a checkout root has to exist on disk. Acquisition order:

  1. ``BAND_SDK_PATH`` — an explicit existing checkout wins outright.
  2. Otherwise the checkout is auto-cloned into ``.deps/`` at the commit uv
     installed the band-sdk package from (PEP 610 direct_url.json).
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
from pathlib import Path

from pa_settings import pa_settings

_SDK_GIT_URL = "https://github.com/band-ai/band-sdk-python"
_DEPS_DIR = Path(__file__).resolve().parents[1] / ".deps"


def toolkit_checkout() -> Path:
    """A checkout root whose ``tests/e2e/baseline`` tree matches the
    installed band-sdk package."""
    override = pa_settings().band_sdk_path
    if override:
        path = override.resolve()
        if not _is_checkout(path):
            raise ModuleNotFoundError(
                f"BAND_SDK_PATH={path} is not a band-sdk-python checkout"
            )
        return path
    return _clone(_DEPS_DIR / "band-sdk-python")


def _clone(dest: Path) -> Path:
    """Shallow-fetch the repo at the installed package's commit (GitHub
    serves arbitrary reachable SHAs), falling back to main if the dist
    carries no VCS record (e.g. a future PyPI install)."""
    commit = _installed_commit()
    if _matches(dest, commit):
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").is_dir():
        _git(dest, "init", "-q")
        _git(dest, "remote", "add", "origin", _SDK_GIT_URL)
    _git(dest, "fetch", "-q", "--depth", "1", "origin", commit or "main")
    _git(dest, "checkout", "-q", "--force", "FETCH_HEAD")
    return dest


def _installed_commit() -> str | None:
    """The git commit the installed band-sdk dist was built from (PEP 610)."""
    try:
        raw = importlib.metadata.distribution("band-sdk").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    return json.loads(raw).get("vcs_info", {}).get("commit_id")


def _matches(dest: Path, commit: str | None) -> bool:
    if not _is_checkout(dest):
        return False
    if commit is None:
        return True
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True
    )
    return head.stdout.strip() == commit


def _is_checkout(path: Path) -> bool:
    return (path / "tests" / "e2e" / "baseline").is_dir()


def _git(dest: Path, *argv: str) -> None:
    subprocess.run(["git", *argv], cwd=dest, capture_output=True, text=True, check=True)
