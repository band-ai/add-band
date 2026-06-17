#!/usr/bin/env python3
"""Render bootstrap scripts from each <harness>/manifest.yaml.

The manifest is the single source of truth for an integration's facts (repo,
ref, skill path, run command, ...). The bootstrap scripts are generated — never
hand-edit them. The web app renders the same minimal snippet from the same
manifest, substituting the user's key for YOUR_BAND_KEY.

Usage:
    python3 scripts/gen.py            # regenerate every integration's scripts
    python3 scripts/gen.py --check    # CI: exit 1 if any committed script is stale

Manifests are intentionally a flat `key: value` subset of YAML so no third-party
parser is needed.
"""
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = {
    "bootstrap.sh": ROOT / "scripts/templates/bootstrap.sh.tmpl",
    "bootstrap.min.sh": ROOT / "scripts/templates/bootstrap.min.sh.tmpl",
}


def parse(path):
    """Parse a flat `key: value` manifest. Values keep everything after the
    first `: ` verbatim (so URLs and piped commands survive)."""
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        fields[key.strip()] = val.strip()
    return fields


def render(template_text, fields, harness):
    """Replace @@TOKEN@@ markers with manifest values + a couple derived ones."""
    values = dict(fields)
    values["name_upper"] = harness.upper().replace("-", "_")
    values["harness_bin"] = fields["run"].split()[0]
    out = template_text
    for key, val in values.items():
        out = out.replace(f"@@{key.upper()}@@", val)
    return out


def main():
    check = "--check" in sys.argv
    stale = []
    for manifest in sorted(ROOT.glob("*/manifest.yaml")):
        harness = manifest.parent.name
        if harness.startswith(("_", ".")):
            continue  # _template and friends are not real integrations
        fields = parse(manifest)
        for name, tmpl in TEMPLATES.items():
            target = manifest.parent / name
            rendered = render(tmpl.read_text(encoding="utf-8"), fields, harness)
            if check:
                current = target.read_text(encoding="utf-8") if target.exists() else None
                if current != rendered:
                    stale.append(str(target.relative_to(ROOT)))
            else:
                target.write_text(rendered, encoding="utf-8")
                target.chmod(0o755)
                print(f"generated {target.relative_to(ROOT)}")
    if check and stale:
        print("stale — run `python3 scripts/gen.py`:\n  " + "\n  ".join(stale), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
