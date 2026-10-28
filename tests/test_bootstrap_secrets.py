"""Hermetic runs of the hermes, nanoclaw and openclaw bootstraps against shims.

Every external command a bootstrap starts (the harness CLI, git, OneCLI, the
hand-off agent, checkout code it sources) is replaced by a shim on PATH that
records its argv and environment. The tests assert the user API key reaches only
the registration step (curl's stdin config, or the register helper's environment)
and no other process, and that a re-run never mints a second agent.

Each bootstrap runs on a pseudo-terminal because the hand-offs redirect stdin
from /dev/tty, which fails without a controlling terminal.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import subprocess
import termios
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
USER_KEY = "user-key-5d1f0c7a-must-not-leak"
AGENT_KEY = "agent-key-93be41"

# Shared shim prelude: append argv + environment to the log named by the shim.
PY_PRELUDE = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
STATE = Path({state!r})
with open({log!r}, "a") as fh:
    fh.write("=== " + json.dumps([Path(sys.argv[0]).name] + sys.argv[1:]) + "\\n")
    fh.write("\\n".join(f"{{k}}={{v}}" for k, v in os.environ.items()) + "\\n")
args = sys.argv[1:]
"""


@dataclass
class Sandbox:
    root: Path
    bin: Path
    home: Path
    state: Path
    log: Path  # every process that must never see the user key
    allowed: Path  # the registration step, which must see it

    def shim(self, name: str, body: str = "", *, log: Path | None = None) -> Path:
        path = self.bin / name
        prelude = PY_PRELUDE.format(state=str(self.state), log=str(log or self.log))
        path.write_text(prelude + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def env(self, **extra: str) -> dict[str, str]:
        return {
            "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
            "HOME": str(self.home),
            "BAND_USER_API_KEY": USER_KEY,
            **extra,
        }

    def records(self, path: Path | None = None) -> list[tuple[list[str], str]]:
        """(argv, environment text) per recorded process."""
        source = path or self.log
        text = source.read_text() if source.exists() else ""
        out = []
        for chunk in re.split(r"^=== ", text, flags=re.MULTILINE)[1:]:
            head, _, body = chunk.partition("\n")
            out.append((json.loads(head), body))
        return out


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    box = Sandbox(
        root=tmp_path,
        bin=tmp_path / "bin",
        home=tmp_path / "home",
        state=tmp_path / "state",
        log=tmp_path / "children.log",
        allowed=tmp_path / "registration.log",
    )
    for d in (box.bin, box.home, box.state):
        d.mkdir()
    return box


def run_on_tty(script: Path, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run `bash script` with a pty as its controlling terminal."""
    master, slave = os.openpty()

    def take_tty() -> None:
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    try:
        return subprocess.run(
            ["bash", str(script)],
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
            preexec_fn=take_tty,
            pass_fds=(slave,),
        )
    finally:
        os.close(slave)
        os.close(master)


def assert_key_isolated(box: Sandbox) -> None:
    children = box.records()
    assert children, "no child process was recorded"
    leaks = [argv for argv, environ in children if USER_KEY in json.dumps(argv) or USER_KEY in environ]
    assert leaks == [], f"user key reached: {leaks}"
    assert USER_KEY in box.allowed.read_text(), "the registration step never received the user key"


def bash_shim(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


# ---------------------------------------------------------------- openclaw

OPENCLAW_BODY = """
accounts = STATE / "accounts.json"
known = json.loads(accounts.read_text()) if accounts.exists() else {}
if args[:2] == ["plugins", "install"] and "--help" in args:
    print("  --accept-capabilities  accept the plugin's requested capabilities")
elif args[:3] == ["config", "get", "channels.openclaw-channel-band.accounts"]:
    if not known:
        sys.exit(1)
    print(json.dumps(known))
elif args[:3] == ["config", "get", "gateway.mode"]:
    sys.exit(1)
elif args[:2] == ["channels", "add"]:
    known[args[args.index("--account") + 1]] = {"enabled": True}
    accounts.write_text(json.dumps(known))
"""

CURL_BODY = """
config = sys.stdin.read()
with open(STATE / "registration.log", "a") as fh:
    fh.write('=== ["curl stdin"]\\n' + config + "\\n")
count_file = STATE / "registrations"
n = int(count_file.read_text()) + 1 if count_file.exists() else 1
count_file.write_text(str(n))
body = {"data": {"agent": {"id": f"agent-{n}"}, "credentials": {"api_key": f"agent-key-{n}"}}}
sys.stdout.write(json.dumps(body) + "\\n201")
"""


def openclaw_box(box: Sandbox) -> dict[str, str]:
    box.allowed = box.state / "registration.log"
    box.shim("openclaw", OPENCLAW_BODY)
    box.shim("curl", CURL_BODY)
    return box.env(BAND_AGENT_NAME="Shim Agent", BAND_AGENT_DESCRIPTION="shim run")


def test_openclaw_keeps_user_key_out_of_openclaw(sandbox: Sandbox):
    env = openclaw_box(sandbox)
    result = run_on_tty(ROOT / "openclaw" / "bootstrap.sh", env, sandbox.root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Registered agent agent-1." in result.stdout
    assert_key_isolated(sandbox)


def test_openclaw_rerun_reuses_the_registered_account(sandbox: Sandbox):
    env = openclaw_box(sandbox)
    first = run_on_tty(ROOT / "openclaw" / "bootstrap.sh", env, sandbox.root)
    assert first.returncode == 0, first.stdout + first.stderr
    second = run_on_tty(ROOT / "openclaw" / "bootstrap.sh", env, sandbox.root)
    assert second.returncode == 0, second.stdout + second.stderr

    assert (sandbox.state / "registrations").read_text() == "1"
    adds = [argv for argv, _ in sandbox.records() if argv[1:3] == ["channels", "add"]]
    assert len(adds) == 1, adds
    assert "agent-1 is already wired" in second.stdout
    restarts = [argv for argv, _ in sandbox.records() if argv[1:3] == ["gateway", "restart"]]
    assert len(restarts) == 2, "the re-run must still restart the gateway"


# ------------------------------------------------------------------ hermes

def test_hermes_keeps_user_and_agent_keys_out_of_children(sandbox: Sandbox):
    hermes_home = sandbox.home / ".hermes"
    gateway_env = sandbox.state / "gateway.env"
    sandbox.shim("uv")
    sandbox.shim("fake-install")
    sandbox.shim(
        "git",
        f"""
if "init" in args:
    Path(args[-1]).mkdir(parents=True)
elif "checkout" in args:
    installer = Path(args[args.index("-C") + 1]) / "install.sh"
    installer.write_text('#!/bin/sh\\nexec {sandbox.bin / "fake-install"} "$@"\\n')
    installer.chmod(0o755)
""",
    )
    sandbox.shim(
        "hermes",
        f"""
if args[:2] == ["config", "env-path"]:
    print({str(gateway_env)!r})
""",
    )
    hermes_py = sandbox.shim(
        "gateway-python",
        f"""
sys.stdin.read()
Path({str(gateway_env)!r}).write_text("BAND_AGENT_ID=" + os.environ["BAND_AGENT_ID"] + "\\n")
""",
    )
    bash_shim(
        hermes_home / "plugins/band/skills/add-band/scripts/register-agent.sh",
        f"""{{ echo "=== [\\"register-agent.sh\\"]"; env; }} >> {sandbox.allowed}
printf 'BAND_AGENT_ID=agent-1\\nBAND_AGENT_API_KEY={AGENT_KEY}\\n'
""",
    )
    env = sandbox.env(
        HERMES_HOME=str(hermes_home),
        HERMES_PY=str(hermes_py),
        BAND_AGENT_NAME="Shim Agent",
    )

    result = run_on_tty(ROOT / "hermes" / "bootstrap.sh", env, sandbox.root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert_key_isolated(sandbox)
    chats = [environ for argv, environ in sandbox.records() if argv[:2] == ["hermes", "chat"]]
    assert len(chats) == 1, "the bootstrap never handed off to hermes chat"
    assert AGENT_KEY not in chats[0]


# ---------------------------------------------------------------- nanoclaw

def test_nanoclaw_keeps_keys_out_of_children_and_scopes_the_vault(sandbox: Sandbox):
    checkout = sandbox.root / "nanoclaw"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "nanoclaw.sh").write_text("")
    (checkout / "setup/lib").mkdir(parents=True)
    # Checkout code the bootstrap sources: dump every shell variable it can see.
    (checkout / "setup/lib/install-slug.sh").write_text(
        "launchd_label() { echo com.nanoclaw.shim; }\n"
        "systemd_unit() { echo nanoclaw-shim; }\n"
        f"{{ echo '=== [\"install-slug.sh\"]'; set; }} >> {sandbox.log}\n"
    )
    for service in ("Library/LaunchAgents/com.nanoclaw.shim.plist", ".config/systemd/user/nanoclaw-shim.service"):
        (sandbox.home / service).parent.mkdir(parents=True, exist_ok=True)
        (sandbox.home / service).write_text("")
    skill = checkout / ".claude/skills/add-band"
    bash_shim(
        skill / "scripts/register-agent.sh",
        f"""{{ echo "=== [\\"register-agent.sh\\"]"; env; }} >> {sandbox.allowed}
printf 'BAND_AGENT_ID=agent-1\\nBAND_AGENT_API_KEY={AGENT_KEY}\\n'
""",
    )
    (skill / "SKILL.md").write_text("skill")
    sandbox.shim("git")
    sandbox.shim("claude")
    sandbox.shim(
        "onecli",
        """
secrets = STATE / "secrets"
if args[:2] == ["secrets", "list"]:
    print(secrets.read_text() if secrets.exists() else "")
elif args[:2] == ["secrets", "create"]:
    secrets.write_text(args[args.index("--name") + 1])
""",
    )
    env = sandbox.env(NANOCLAW_HOME=str(checkout), BAND_BASE_URL="https://staging.example.test/")

    for _ in range(2):
        result = run_on_tty(ROOT / "nanoclaw" / "bootstrap.sh", env, sandbox.root)
        assert result.returncode == 0, result.stdout + result.stderr

    assert_key_isolated(sandbox)
    records = sandbox.records()
    assert sum(1 for argv, _ in sandbox.records(sandbox.allowed) if argv == ["register-agent.sh"]) == 1
    assert any(argv == ["install-slug.sh"] for argv, _ in records), "setup detection never sourced the checkout helper"
    claude = [environ for argv, environ in records if argv[0] == "claude"]
    assert len(claude) == 2 and all(AGENT_KEY not in environ for environ in claude)
    create = next(argv for argv, _ in records if argv[:3] == ["onecli", "secrets", "create"])
    assert create[create.index("--host-pattern") + 1] == "staging.example.test"
    dotenv = (checkout / ".env").read_text().splitlines()
    assert dotenv == [
        "BAND_AGENT_ID=agent-1",
        f"BAND_AGENT_API_KEY={AGENT_KEY}",
        "BAND_BASE_URL=https://staging.example.test",
    ]
