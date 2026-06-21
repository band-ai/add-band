#!/usr/bin/env python3
"""Validate the integration catalog.

Every top-level integration folder is in exactly one of two states:

  - **participating** — has a ``manifest.yaml`` (metadata) and a hand-authored
    ``bootstrap.sh`` (the full, runnable snippet). check.py validates these.
  - **stub** — README-only, no snippet yet. Listed in :data:`STUB_ONLY` so it is
    a deliberate opt-out rather than a silent gap.

Bootstrap snippets are *not* generated and have no common shape — Hermes installs a
plugin into the gateway and hands off to a setup skill; OpenClaw clones a repo and runs
the openclaw CLI. So this script validates structure, not content.

The minimal copy-paste version (what the web app shows in a small code block) is
not a separate file — it's a projection of ``bootstrap.sh``:

  - If the script carries ``# >>> band:mini`` / ``# <<< band:mini`` markers, the
    mini is the lines inside those regions, in file order, across every region.
  - If it carries no markers, the mini is the whole script — so a script that is
    already short enough needs no markers at all.

Either way the mini is stripped of comments, shebangs, and blank lines, so the
generated snippet is pure commands, and is capped at :data:`MINI_MAX_LINES` lines
so it always fits the web block.

    python3 scripts/check.py            # validate the whole catalog (CI gate)
    python3 scripts/check.py --mini hermes   # print hermes' minimal snippet
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

# Every bootstrap obtains the Band user API key itself — it prompts for it (reading from
# /dev/tty, since `curl ... | bash` makes stdin the script) or accepts a pre-set
# BAND_USER_API_KEY from the environment. We assert the variable name appears in the mini
# the web app serves; the web app hands the user a key to paste, it does not edit the script.
KEY_VAR = "BAND_USER_API_KEY"

# Markers bounding the minimal copy-paste snippet inside bootstrap.sh. Optional:
# a script with no markers uses its whole (comment-stripped) body as the mini.
MINI_START = "# >>> band:mini"
MINI_END = "# <<< band:mini"
MINI_MAX_LINES = 25  # accumulative, across all regions; counts command lines only


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


def strip_shell_comment(line: str) -> str:
    """Drop a shell trailing comment: the first unquoted ``#`` that begins a word.

    Quote-aware, so a ``#`` inside a string or URL is preserved; a ``#`` at line
    start or after whitespace (and outside quotes) begins a comment and is cut.
    A whole-line comment or shebang collapses to ``""``. For any line with no
    ``#`` the result is just the line, right-stripped.
    """
    out: list[str] = []
    quote: str | None = None
    prev_ws = True  # start of line counts as a word boundary
    for ch in line:
        if quote is not None:
            out.append(ch)
            if ch == quote:
                quote = None
            prev_ws = False
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
            prev_ws = False
        elif ch == "#" and prev_ws:
            break
        else:
            out.append(ch)
            prev_ws = ch.isspace()
    return "".join(out).rstrip()


def extract_mini(text: str) -> tuple[list[str], list[str], bool]:
    """Return ``(mini_lines, problems, has_markers)`` for a bootstrap script.

    ``mini_lines`` is the copy-paste projection: the lines inside ``band:mini``
    regions if any exist, otherwise the whole script — comment/shebang/blank lines
    stripped either way. ``problems`` flags unbalanced or nested markers.
    """
    lines = text.splitlines()
    has_markers = any(s in (MINI_START, MINI_END) for s in (l.strip() for l in lines))
    problems: list[str] = []
    raw: list[str] = []

    if has_markers:
        open_at: int | None = None
        for i, line in enumerate(lines, 1):
            marker = line.strip()
            if marker == MINI_START:
                if open_at is not None:
                    problems.append(
                        f"nested '{MINI_START}' at line {i} (region opened at line {open_at} not closed)"
                    )
                open_at = i
            elif marker == MINI_END:
                if open_at is None:
                    problems.append(f"'{MINI_END}' at line {i} has no matching start")
                else:
                    open_at = None
            elif open_at is not None:
                raw.append(line)
        if open_at is not None:
            problems.append(f"unclosed '{MINI_START}' at line {open_at}")
    else:
        raw = lines

    mini = [s for s in (strip_shell_comment(l) for l in raw) if s.strip()]
    return mini, problems, has_markers


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

    mini, mini_problems, has_markers = extract_mini(bootstrap.read_text(encoding="utf-8"))
    problems.extend(f"{name}: {p}" for p in mini_problems)

    if not mini:
        if not mini_problems:
            problems.append(f"{name}: bootstrap.sh has no command lines")
    elif len(mini) > MINI_MAX_LINES:
        if has_markers:
            problems.append(
                f"{name}: mini snippet is {len(mini)} lines, over the {MINI_MAX_LINES}-line cap "
                f"(trim the '{MINI_START}' region(s) so it fits a small code block)"
            )
        else:
            problems.append(
                f"{name}: bootstrap.sh has {len(mini)} command lines, over the {MINI_MAX_LINES}-line cap "
                f"(wrap the copy-paste subset in '{MINI_START}' / '{MINI_END}' markers)"
            )

    if mini and KEY_VAR not in "\n".join(mini):
        problems.append(
            f"{name}: the mini snippet must handle {KEY_VAR} "
            f"(prompt for it, or accept it from the environment)"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if len(argv) >= 2 and argv[0] == "--mini":
        name = argv[1]
        bootstrap = ROOT / name / "bootstrap.sh"
        if not bootstrap.exists():
            print(f"no {name}/bootstrap.sh", file=sys.stderr)
            return 1
        mini, mini_problems, _ = extract_mini(bootstrap.read_text(encoding="utf-8"))
        if mini_problems:
            print("\n".join(mini_problems), file=sys.stderr)
            return 1
        print("\n".join(mini))
        return 0

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
