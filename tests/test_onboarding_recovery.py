"""Exercise onboarding diagnostics through real HTTP requests and subprocesses."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET = "credential-must-not-appear"
ERROR_BODIES = [
    json.dumps(
        {"error": {"code": "unauthorized", "message": SECRET, "request_id": "test"}}
    ),
    json.dumps({"unexpected": SECRET}),
    f"<html>{SECRET}</html>",
]


@pytest.fixture
def peer():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.server.requests.append((self.path, self.headers.get("X-API-Key")))
            if self.server.responses:
                status, response = self.server.responses.pop(0)
                self.respond(status, response)
                return
            if self.server.lifecycle:
                if self.path.endswith("/participants"):
                    self.respond(
                        200,
                        {
                            "data": {
                                "id": "agent-id",
                                "role": "member",
                                "status": "active",
                                "type": "Agent",
                            }
                        },
                    )
                elif self.path.endswith("/messages"):
                    self.server.sent_content = json.loads(body)["message"]["content"]
                    self.respond(
                        200,
                        {
                            "data": {
                                "id": "message-id",
                                "recipients": [],
                                "success": True,
                            }
                        },
                    )
                else:
                    self.respond(
                        201,
                        {
                            "data": {
                                "id": "room-id",
                                "inserted_at": "2026-01-01T00:00:00Z",
                                "updated_at": "2026-01-01T00:00:00Z",
                            }
                        },
                    )
                return
            self.send_response(self.server.status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(self.server.body.encode())

        def respond(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            self.respond(
                200,
                {
                    "data": [
                        {
                            "id": "reply",
                            "sender_id": "agent-id",
                            "sender_type": "Agent",
                            "message_type": self.server.message_type,
                            "content": self.server.sent_content
                            + " provider HTTP 401 "
                            + SECRET,
                        }
                    ],
                    "metadata": {"has_more": False, "limit": 50},
                },
            )

        def do_DELETE(self):
            self.server.deletions += 1
            self.respond(403, {"error": SECRET})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.status = 401
    server.body = ERROR_BODIES[0]
    server.requests = []
    server.responses = []
    server.lifecycle = False
    server.message_type = "text"
    server.deletions = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def run_helper(path, env, cwd, executable):
    return subprocess.run(
        check=False,
        args=[executable, str(ROOT / "scripts" / path)],
        env={**os.environ, **env},
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.mark.parametrize("status", [401, 403, 500])
@pytest.mark.parametrize("body", ERROR_BODIES)
def test_registration_failure_does_not_expose_body_or_retry(
    peer, tmp_path, status, body
):
    server, url = peer
    server.status, server.body = status, body
    result = run_helper(
        "register-agent.sh",
        {
            "BAND_USER_API_KEY": SECRET,
            "BAND_BASE_URL": url,
            "BAND_AGENT_NAME": "Test Agent",
            "BAND_AGENT_DESCRIPTION": "test",
        },
        tmp_path,
        "bash",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert SECRET not in result.stderr
    assert f"HTTP {status}" in result.stderr
    assert ("ONBOARDING-RECOVERY.md" in result.stderr) == (status in (401, 403))
    assert server.requests == [("/api/v1/me/agents/register", SECRET)]


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (
            201,
            '{"data":{"agent":{"id":"agent-id"},"credentials":{"api_key":"agent-key"}}}',
            0,
        ),
        (201, "{}", 1),
        (422, '{"error":"name has already been taken"}', 1),
    ],
)
def test_registration_preserves_success_and_collision_contract(
    peer, tmp_path, status, body, expected
):
    server, url = peer
    server.status, server.body = status, body
    result = run_helper(
        "register-agent.sh",
        {
            "BAND_USER_API_KEY": SECRET,
            "BAND_BASE_URL": url,
            "BAND_AGENT_NAME": "Test Agent",
            "BAND_AGENT_DESCRIPTION": "test",
        },
        tmp_path,
        "bash",
    )
    assert result.returncode == expected
    assert len(server.requests) == 1
    assert SECRET not in result.stdout + result.stderr
    if expected == 0:
        assert result.stdout == "BAND_AGENT_ID=agent-id\nBAND_AGENT_API_KEY=agent-key\n"
    if status == 422:
        assert "name has already been taken" in result.stderr


@pytest.mark.skipif(
    importlib.util.find_spec("band") is None,
    reason="requires band-sdk in test interpreter",
)
@pytest.mark.parametrize("status", [401, 403, 500])
@pytest.mark.parametrize("body", ERROR_BODIES)
def test_verification_classifies_actual_band_status_without_raw_errors(
    peer, tmp_path, status, body
):
    server, url = peer
    server.status, server.body = status, body
    # An explicit corrected invocation must beat stale persisted configuration.
    (tmp_path / ".env").write_text("BAND_REST_URL=http://127.0.0.1:1\n")
    result = run_helper(
        "verify_agent_reply.py",
        {
            "BAND_USER_API_KEY": SECRET,
            "BAND_REST_URL": url,
            "VERIFY_AGENT_ID": "agent-id",
            "VERIFY_AGENT_NAME": "Test Agent",
        },
        tmp_path,
        sys.executable,
    )
    assert result.returncode == 1
    assert SECRET not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert f"HTTP {status}" in result.stderr
    assert ("ONBOARDING-RECOVERY.md" in result.stderr) == (status in (401, 403))
    assert server.requests == [("/api/v1/me/chats", SECRET)]


@pytest.mark.skipif(
    importlib.util.find_spec("band") is None,
    reason="requires band-sdk in test interpreter",
)
@pytest.mark.parametrize(
    "message_type,timeout,expected,notice",
    [
        ("text", "10", 0, "replied with the check token"),
        ("error", "10", 1, "reported an error"),
        ("text", "0", 1, "timeout alone does not identify"),
    ],
)
def test_verification_keeps_provider_timeout_and_cleanup_separate(
    peer, tmp_path, message_type, timeout, expected, notice
):
    server, url = peer
    server.lifecycle = True
    server.message_type = message_type
    result = run_helper(
        "verify_agent_reply.py",
        {
            "BAND_USER_API_KEY": SECRET,
            "BAND_REST_URL": url,
            "VERIFY_AGENT_ID": "agent-id",
            "VERIFY_AGENT_NAME": "Test Agent",
            "VERIFY_TIMEOUT_SECONDS": timeout,
        },
        tmp_path,
        sys.executable,
    )
    output = result.stdout + result.stderr
    assert result.returncode == expected, output
    assert notice in output
    assert SECRET not in output
    assert "ONBOARDING-RECOVERY.md" not in output
    assert "could not delete check room" in output
    assert server.deletions == 1


@pytest.mark.parametrize("harness", ["claude", "codex", "cursor"])
def test_prompt_provisioning_retains_tom_before_jerry_auth_failure(
    peer, tmp_path, harness
):
    server, url = peer
    server.responses = [
        (
            201,
            {
                "data": {
                    "agent": {"id": "tom-id"},
                    "credentials": {"api_key": "tom-key"},
                }
            },
        ),
        (
            401,
            {
                "error": {
                    "code": "unauthorized",
                    "message": SECRET,
                    "request_id": "test",
                }
            },
        ),
    ]
    prompt = (ROOT / harness / "bootstrap-prompt.md").read_text()
    block = next(
        block
        for block in re.findall(r"```bash\n(.*?)```", prompt, re.DOTALL)
        if "REGISTER_URL=" in block
    )
    output = tmp_path / "agents"
    block = (
        block.replace("<out>", str(output))
        .replace("<user-api-key-from-step-1>", SECRET)
        .replace("<BAND_REST_URL from Step 1>", url)
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(f"""#!{sys.executable}
import os, shutil, sys
if any('raw.githubusercontent.com' in arg for arg in sys.argv):
    shutil.copyfile({str(ROOT / "scripts/register-agent.sh")!r}, sys.argv[sys.argv.index('-o') + 1])
else:
    os.execv({shutil.which("curl")!r}, ['curl', *sys.argv[1:]])
""")
    uv = bin_dir / "uv"
    uv.write_text(f"""#!{sys.executable}
import os, sys
os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[sys.argv.index('python') + 1:]])
""")
    curl.chmod(0o755)
    uv.chmod(0o755)
    result = subprocess.run(
        check=False,
        args=["bash", "-c", block],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "TMPDIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads((output / "agent_config.yaml").read_text()) == {
        "tom_agent": {"agent_id": "tom-id", "api_key": "tom-key"},
    }
    assert (output / ".env").read_text() == f"BAND_REST_URL={url}\n"
    assert server.requests == [("/api/v1/me/agents/register", SECRET)] * 2
    assert SECRET not in result.stdout + result.stderr
    assert all(SECRET not in path.read_text() for path in output.iterdir())
