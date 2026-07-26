"""Acquire a band-sdk-python checkout for the baseline toolkit.

The toolkit is not shipped in the band-sdk wheel; it lives in the repo's tests
tree, so a checkout root has to exist on disk. Acquisition order:

  1. ``BAND_SDK_PATH`` — an explicit existing checkout wins outright. This is
     the development escape hatch for hacking on the suite and SDK together,
     so it is shape-checked only — never identity- or commit-checked.
  2. Otherwise the checkout is auto-cloned into ``.deps/`` at the commit uv
     installed the band-sdk package from (PEP 610 direct_url.json). A dist
     with no VCS record (a registry install) has no commit to match, so main
     is re-fetched every time rather than trusting whatever the cache holds.
"""

from __future__ import annotations

import fcntl
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
    serves arbitrary reachable SHAs); with no commit to match, (re)fetch main.

    The flock serializes concurrent processes importing driver.sdk (parallel
    pytest sessions, tooling) so one mutation can't race another's import.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest.parent / ".checkout.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        commit = _installed_commit()
        if commit and _matches(dest, commit):
            return dest
        dest.mkdir(exist_ok=True)
        if not (dest / ".git").is_dir():
            _git(dest, "init", "-q")
            _git(dest, "remote", "add", "origin", _SDK_GIT_URL)
        else:
            _require_origin(dest)
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


def _matches(dest: Path, commit: str) -> bool:
    if not _is_checkout(dest):
        return False
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True
    )
    return head.stdout.strip() == commit


def _require_origin(dest: Path) -> None:
    """Refuse to mutate a cache directory that isn't our clone — force-checkout
    into an unrelated repository would destroy it."""
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=dest,
        capture_output=True,
        text=True,
    )
    origin = result.stdout.strip()
    if origin != _SDK_GIT_URL:
        raise RuntimeError(
            f"{dest} origin is {origin or '<none>'!r}, expected {_SDK_GIT_URL} — "
            "remove the directory, or point BAND_SDK_PATH at your checkout"
        )


def _is_checkout(path: Path) -> bool:
    return (path / "tests" / "e2e" / "baseline").is_dir()


def _git(dest: Path, *argv: str) -> None:
    """Run git in `dest`; on failure surface the captured output — auth
    failures and missing commits are otherwise opaque import-time errors."""
    result = subprocess.run(["git", *argv], cwd=dest, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"`git {' '.join(argv)}` in {dest} exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
