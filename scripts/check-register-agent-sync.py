#!/usr/bin/env python3
"""Check that shared register-agent.sh copies match the catalog source.

The source of truth lives at ``add-band/scripts/register-agent.sh``. Integration
repos may vendor the same helper under their own add-band skill so their
copy-paste bootstrap can run without fetching another file. This checker keeps
those copies honest:

  python3 scripts/check-register-agent-sync.py
      Compare copies that exist locally; skip missing sibling repos/paths.

  python3 scripts/check-register-agent-sync.py --strict
      Also fail when any declared copy is missing. Use this in a multi-repo CI
      job that checks out add-band plus nanoclaw-band side by side.

  python3 scripts/check-register-agent-sync.py --sync
      Copy the canonical helper into every declared repo that exists locally.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "scripts" / "register-agent.sh"
SIBLINGS = ROOT.parent


@dataclass(frozen=True)
class Target:
    name: str
    repo: Path
    path: Path

    @property
    def full_path(self) -> Path:
        return self.repo / self.path


TARGETS = [
    Target(
        "nanoclaw-band",
        SIBLINGS / "nanoclaw-band",
        Path(".claude/skills/add-band/scripts/register-agent.sh"),
    ),
    # Local staging name used before github.com/band-ai/nanoclaw-band exists.
    Target(
        "nanoclaw-thenvoi",
        SIBLINGS / "nanoclaw-thenvoi",
        Path(".claude/skills/add-band/scripts/register-agent.sh"),
    ),
    # The Hermes plugin vendors the bash helper alongside its Python
    # register_agent.py, under the package's own skills tree (not .claude/).
    Target(
        "hermes-band-platform",
        SIBLINGS / "hermes-band-platform",
        Path("hermes_band_platform/skills/add-band/scripts/register-agent.sh"),
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail if any declared sibling repo or copy is missing",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="copy the canonical helper into every declared sibling repo that exists",
    )
    return parser.parse_args()


def sync_targets(canonical: Path) -> list[str]:
    messages: list[str] = []
    for target in TARGETS:
        if not target.repo.exists():
            messages.append(f"skip {target.name}: repo not found at {target.repo}")
            continue
        target.full_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(canonical, target.full_path)
        target.full_path.chmod(canonical.stat().st_mode)
        messages.append(f"synced {target.name}: {target.full_path}")
    return messages


def check_targets(canonical: Path, strict: bool) -> tuple[list[str], list[str]]:
    canonical_bytes = canonical.read_bytes()
    problems: list[str] = []
    messages: list[str] = []

    for target in TARGETS:
        if not target.repo.exists():
            msg = f"{target.name}: repo not found at {target.repo}"
            (problems if strict else messages).append(msg)
            continue
        if not target.full_path.exists():
            msg = f"{target.name}: missing {target.full_path.relative_to(target.repo)}"
            (problems if strict else messages).append(msg)
            continue
        if target.full_path.read_bytes() != canonical_bytes:
            problems.append(
                f"{target.name}: {target.full_path} differs from {canonical}"
            )
        else:
            messages.append(f"{target.name}: in sync")

    return problems, messages


def main() -> int:
    args = parse_args()
    if not CANONICAL.exists():
        print(f"missing canonical helper: {CANONICAL}", file=sys.stderr)
        return 1

    if args.sync:
        for message in sync_targets(CANONICAL):
            print(message)
        return 0

    problems, messages = check_targets(CANONICAL, strict=args.strict)
    for message in messages:
        print(message)
    if problems:
        print("register-agent helper drift check failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "Run `python3 scripts/check-register-agent-sync.py --sync` from add-band "
            "after checking out the sibling integration repos.",
            file=sys.stderr,
        )
        return 1

    print("OK — register-agent helper copies are in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
