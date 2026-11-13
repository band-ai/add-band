#!/usr/bin/env python3
"""Exercise real onboarding conversations against local Band registration peers.

The question gate recognizes site-related questions, not full linguistic intent.
This tests conversation, registration and persistence; it does not test live agents.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import yaml
from check import STUB_ONLY
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
USER_KEY = "band_u_recovery_fixture_never_print"
SITE_QUESTION = re.compile(
    r"(?:website|browser|site|address|url|where.{0,40}(?:open|use|access).{0,20}band)",
    re.IGNORECASE,
)


@contextmanager
def registration_peer(status):
    requests = []
    identities = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
            )
            name = body.get("agent", {}).get("name", "")
            requests.append(
                {
                    "path": self.path,
                    "name": name,
                    "correct_key": self.headers.get("X-API-Key") == USER_KEY,
                }
            )
            code = status if requests[-1]["correct_key"] else 401
            if code == 201:
                identity = {
                    "agent_id": str(uuid.uuid4()),
                    "api_key": "band_a_fixture_" + uuid.uuid4().hex,
                }
                identities[name] = identity
                payload = {
                    "data": {
                        "agent": {"id": identity["agent_id"]},
                        "credentials": {"api_key": identity["api_key"]},
                    }
                }
            else:
                payload = {"error": "API key not linked to a user or agent"}
            encoded = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests, identities
        finally:
            server.shutdown()
            thread.join()


def redact(text, secrets):
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def scrub_artifacts(directory, secrets):
    for path in directory.rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                text = path.read_text()
            except (UnicodeError, OSError):
                continue
            cleaned = redact(text, secrets)
            if text != cleaned:
                path.write_text(cleaned)


def invoke(harness, cwd, env, prompt, session, turn, timeout):
    if harness == "claude":
        command = [
            "claude",
            "-p",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            "Bash,Read,Edit,Write,Glob,Grep",
            "--output-format",
            "text",
            "--resume" if turn > 1 else "--session-id",
            session,
            prompt,
        ]
    elif harness == "codex":
        command = ["codex", "exec", "--sandbox", "danger-full-access"]
        if turn > 1:
            command += ["resume", session]
        command += [
            "--json",
            "--skip-git-repo-check",
            "-o",
            str(cwd / f"answer-{turn}.txt"),
            prompt,
        ]
    elif harness == "cursor":
        if turn == 1:
            created = subprocess.run(
                ["agent", "create-chat"],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
            session = created.stdout.strip()
        command = [
            "agent",
            "-p",
            "--force",
            "--output-format",
            "text",
            "--resume",
            session,
        ]
        if env.get("CURSOR_MODEL"):
            command += ["--model", env["CURSOR_MODEL"]]
        command += [prompt]
    else:
        raise ValueError(f"No CLI driver for catalog harness {harness}")
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    raw = completed.stdout + completed.stderr
    secrets = sensitive_values(env)
    (cwd / f"cli-{turn}.log").write_text(redact(raw, secrets))
    if completed.returncode:
        raise AssertionError(
            f"{harness} turn {turn} exited {completed.returncode}; see cli-{turn}.log"
        )
    if any(secret in raw for secret in secrets):
        raise AssertionError(f"{harness} exposed a credential in diagnostics")
    if harness == "codex":
        events = [
            json.loads(line)
            for line in completed.stdout.splitlines()
            if line.startswith("{")
        ]
        threads = [
            event["thread_id"]
            for event in events
            if event.get("type") == "thread.started"
        ]
        assert len(threads) == 1, "Missing unique Codex thread ID"
        if turn > 1:
            assert threads[0] == session, "Codex resumed a different conversation"
        session = threads[0]
    answer = (
        (cwd / f"answer-{turn}.txt").read_text()
        if harness == "codex"
        else completed.stdout
    )
    (cwd / f"answer-{turn}.txt").write_text(redact(answer, secrets))
    return answer, session


def asks_site(answer):
    return any(
        SITE_QUESTION.search(question)
        for sentence in re.split(r"(?<=[.!])\s+|\n", answer)
        for question in re.findall(r"[^?]*\?", sentence)
    )


def check_state(directory, base, websocket, identities):
    settings = dotenv_values(directory / ".env")
    assert settings.get("BAND_REST_URL") == base, "Persisted REST destination differs"
    assert settings.get("BAND_WS_URL") == websocket, "Persisted WS destination differs"
    assert USER_KEY not in (directory / ".env").read_text(), "User key persisted"
    state = yaml.safe_load((directory / "agent_config.yaml").read_text())
    for role, name in (("tom_agent", "Tom"), ("jerry_agent", "Jerry")):
        assert identities[name].items() <= state[role].items(), (
            f"Wrong {name} identity/destination"
        )
    assert USER_KEY not in (directory / "agent_config.yaml").read_text(), (
        "User key persisted"
    )


def sensitive_values(env):
    return {
        value
        for key, value in env.items()
        if len(value) >= 8 and re.search(r"(?:KEY|TOKEN|SECRET|PASSWORD)$", key)
    } | {USER_KEY}


def exercise(harness, output, recovery, timeout):
    cwd = output / ("wrong-site" if recovery else "success")
    cwd.mkdir(parents=True)
    (cwd / harness).mkdir()
    (cwd / "scripts").mkdir()
    for source in (
        f"{harness}/bootstrap-prompt.md",
        "scripts/register-agent.sh",
        "ONBOARDING-RECOVERY.md",
    ):
        shutil.copy2(ROOT / source, cwd / source)
    with registration_peer(401) as cloud, registration_peer(201) as company:
        cloud_url, cloud_requests, _ = cloud
        company_url, company_requests, identities = company
        base = cloud_url if recovery else company_url
        websocket = "ws://127.0.0.1:39001/confirmed-company-socket"
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("BAND_", "THENVOI_")) and key != "CLAUDECODE"
        }
        env.update(
            BAND_USER_API_KEY=USER_KEY,
            BAND_BASE_URL=base,
            BAND_REST_URL=base,
            BAND_WS_URL="ws://127.0.0.1:39002/cloud-socket" if recovery else websocket,
        )
        prompt = f"""Follow {harness}/bootstrap-prompt.md in this checkout for my Tom/Jerry setup.
This exercise ends after registration and credential/endpoint persistence (Steps 5 and the
configuration portion of Step 7). Do not fetch examples, install a project, start agents or
run reply verification. Use scripts/register-agent.sh and ONBOARDING-RECOVERY.md from this
checkout, not their remote copies. Do not modify those source instructions/helper files.
All unrelated choices are settled: direct Anthropic adapter, output ./agents, names Tom
and Jerry, default character descriptions. The Band user key is already in BAND_USER_API_KEY;
read it locally without printing or persisting it. The initial REST/WS settings are exported.
Use the prompt's configuration shape (agent_config.yaml and .env). You may use Python with
PyYAML/python-dotenv through uv. Perform the actual local registration calls, not a simulation.
Follow the instructions when a step cannot complete; ordinary chat is available for questions.
Keep keys out of your answer and diagnostics. Limit Band requests to the supplied loopback
addresses. Stop when this scoped work completes or you need my answer.
"""
        answer, session = invoke(
            harness, cwd, env, prompt, str(uuid.uuid4()), 1, timeout
        )
        if recovery:
            assert len(cloud_requests) == 1, (
                "Expected one rejected registration without retries"
            )
            assert not company_requests, (
                "Reached company before receiving destination context"
            )
            config = cwd / "agents/agent_config.yaml"
            assert not config.exists() or not yaml.safe_load(config.read_text()), (
                "Persisted invented identity"
            )
            assert asks_site(answer), (
                "Assistant did not ask for the usual Band site/address"
            )
            reply = f"""I normally open Band at https://company-band.example.test.
Our administrator confirmed that this deployment's REST connection base for this local test is
{company_url} and its WebSocket URL is {websocket}. The user key already supplied belongs to
that company deployment. Please configure those confirmed settings for me and resume the
unfinished registration/persistence work in ./agents. Do not start agents or fetch examples.
"""
            answer, session = invoke(harness, cwd, env, reply, session, 2, timeout)
            assert len(cloud_requests) == 1, "Retried the rejected destination"
        else:
            assert not asks_site(answer), (
                "Successful setup introduced a deployment question"
            )
            assert not cloud_requests, (
                "Successful setup contacted the wrong destination"
            )
        assert len(company_requests) == 2, (
            "Expected exactly two successful registrations"
        )
        assert sorted(item["name"] for item in company_requests) == ["Jerry", "Tom"]
        assert all(
            item["correct_key"] and item["path"] == "/api/v1/me/agents/register"
            for item in cloud_requests + company_requests
        ), "Wrong registration request"
        for path in (cwd / "agents/.env", cwd / "agents/agent_config.yaml"):
            assert not any(
                secret in path.read_text() for secret in sensitive_values(env)
            ), "Credential leaked to generated configuration"
        check_state(cwd / "agents", company_url, websocket, identities)
        (cwd / "evidence.json").write_text(
            json.dumps(
                {
                    "harness": harness,
                    "scenario": cwd.name,
                    "cloud_requests": cloud_requests,
                    "company_requests": company_requests,
                    "persisted_endpoints_match": True,
                    "question_gate": "site-related question heuristic; not a semantic judge",
                    "live_agent_verification": "not exercised",
                },
                indent=2,
            )
        )
        print(
            f"PASS {harness} {cwd.name}: registration destinations, conversation gate and persisted state"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", choices=sorted(STUB_ONLY), required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--timeout", type=int, default=300, help="Maximum seconds per CLI turn"
    )
    args = parser.parse_args()
    output = (
        args.output_dir or Path(tempfile.mkdtemp(prefix="band-recovery-"))
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    print(f"Artifacts: {output}", flush=True)
    try:
        exercise(args.harness, output, True, args.timeout)
        exercise(args.harness, output, False, args.timeout)
    finally:
        scrub_artifacts(output, sensitive_values(os.environ))


if __name__ == "__main__":
    main()
