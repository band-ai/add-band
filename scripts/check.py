#!/usr/bin/env python3
"""Validate the integration catalog.

Every top-level integration folder is in exactly one of two states:

  - **participating** — has a ``manifest.yaml`` (metadata) and a hand-authored
    ``bootstrap.sh`` (the full, runnable snippet). check.py validates these.
  - **stub** — README-only, no snippet yet. Listed in :data:`STUB_ONLY` so it is
    a deliberate opt-out rather than a silent gap.

Bootstrap snippets are *not* generated and have no common shape — Hermes clones a
plugin repo and hands a skill to the gateway; OpenClaw runs a couple of curls and
the openclaw CLI. So this script validates structure, not content.

The web app hands the user a snippet that exports their key as
``BAND_USER_API_KEY`` and then runs ``bootstrap.sh``; the snippet consumes that
env var, prompting for it when it's absent. This script enforces that each
``bootstrap.sh`` references that variable.

    python3 scripts/check.py            # validate the whole catalog (CI gate)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Top-level dirs that are not integrations.
STRUCTURAL = {"scripts", "tests"}

# README-only stubs with no bootstrap yet. Listing one here is a deliberate
# opt-out; the drift test fails for any unclassified folder.
STUB_ONLY: set[str] = set()

REQUIRED_MANIFEST_FIELDS = {"name", "repo", "connects_via", "status", "summary"}
VALID_STATUSES = {"available", "planned"}

# The user's key reaches the snippet as the BAND_USER_API_KEY env var (exported
# by the web app's snippet, or prompted for when absent). bootstrap.sh must
# reference this variable so it is actually wired to the key.
KEY_ENV_VAR = "BAND_USER_API_KEY"


def integration_dirs() -> set[str]:
    """Top-level candidate integration folders (excludes meta/structural dirs)."""
    return {
        p.name
        for p in ROOT.iterdir()
        if p.is_dir()
        and not p.name.startswith((".", "_"))
        and p.name not in STRUCTURAL
    }


def participating_dirs() -> set[str]:
    """Integration folders that ship a manifest (and so are validated)."""
    return {d for d in integration_dirs() if (ROOT / d / "manifest.yaml").exists()}


def parse_manifest(path: Path) -> dict[str, str]:
    """Parse a flat ``key: value`` manifest (everything after the first ``: ``)."""
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, val = line.partition(":")
        if sep:
            fields[key.strip()] = val.strip()
    return fields


def validate_integration(name: str) -> list[str]:
    """Return a list of problems for a participating integration (empty == ok)."""
    problems: list[str] = []
    d = ROOT / name

    fields = parse_manifest(d / "manifest.yaml")
    missing = REQUIRED_MANIFEST_FIELDS - set(fields)
    if missing:
        problems.append(f"{name}: manifest.yaml missing fields {sorted(missing)}")
    status = fields.get("status")
    if status is not None and status not in VALID_STATUSES:
        problems.append(f"{name}: status '{status}' not in {sorted(VALID_STATUSES)}")

    bootstrap = d / "bootstrap.sh"
    if not bootstrap.exists():
        problems.append(
            f"{name}: no bootstrap.sh (participating integrations must ship one)"
        )
        return problems

    if KEY_ENV_VAR not in bootstrap.read_text(encoding="utf-8"):
        problems.append(
            f"{name}: bootstrap.sh must consume the user key via ${KEY_ENV_VAR} "
            f"(exported by the web app's snippet, or prompted for when absent)"
        )

    return problems


def main() -> int:
    problems: list[str] = []

    # Completeness: every folder is participating or an explicit stub.
    for d in sorted(integration_dirs() - participating_dirs() - STUB_ONLY):
        problems.append(
            f"{d}: unclassified — add manifest.yaml + bootstrap.sh to participate, "
            f"or add '{d}' to STUB_ONLY in scripts/check.py"
        )
    for d in sorted(STUB_ONLY - integration_dirs()):
        problems.append(f"{d}: in STUB_ONLY but the folder does not exist")
    for d in sorted(STUB_ONLY & participating_dirs()):
        problems.append(f"{d}: in STUB_ONLY but has a manifest.yaml — remove it from STUB_ONLY")

    # Per-integration validation.
    for d in sorted(participating_dirs()):
        problems.extend(validate_integration(d))

    if problems:
        print("Integration catalog check failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(
        f"OK — {len(participating_dirs())} integration(s) valid, "
        f"{len(STUB_ONLY)} stub(s): "
        f"{', '.join(sorted(participating_dirs())) or '—'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
