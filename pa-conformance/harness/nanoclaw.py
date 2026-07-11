"""NanoClaw runner.

Unlike Hermes/OpenClaw there is no published image: stacks/nanoclaw/prepare.sh
must have materialized a Band-wired checkout (main + the band/adapter payload
+ pinned SDK deps) and built the host/agent images first — the runner points
at it via NANOCLAW_SRC and owns only runtime concerns.

Runtime shape:
  - the compose stack is postgres + onecli + the socket-mounted host, which
    spawns per-agent sibling containers through /var/run/docker.sock.
    DOCKER_GID is computed from the socket at runtime, never hardcoded
    (host-specific by design).
  - identity is injected via the checkout's .env (BAND_AGENT_ID /
    BAND_AGENT_API_KEY), so no registration happens here.
  - NanoClaw routes per registered messaging group, so driver-created rooms
    must be wired in: attach_room() registers the room as an agent group
    (setup/index.ts --step register), adds the reply destination, and
    restarts the group.

Readiness is the host serving its CLI (the `ncl` unix socket answering); the
Band-side proof of life is the liveness test itself.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from pa_settings import pa_settings

from harness.compose import ComposeStack
from harness.contract import BandIdentity, Harness, wait_for

_NCL = ("pnpm", "exec", "tsx", "src/cli/client.ts")
_Q = ("pnpm", "exec", "tsx", "scripts/q.ts", "data/v2.db")


def _agent_image_base(src: Path) -> str:
    """Mirror of setup/lib/install-slug.sh's container_image_base():
    `nanoclaw-agent-v2-<sha1(checkout path)[:8]>` — container/build.sh derives
    the tag from the checkout path so two installs on one host can't clobber
    each other, and the compose env must name the same image prepare.sh built.
    """
    slug = hashlib.sha1(str(src).encode()).hexdigest()[:8]
    return f"nanoclaw-agent-v2-{slug}"


class NanoClawHarness(Harness):
    name = "nanoclaw"
    ready_timeout_s = 300.0  # postgres + onecli + host cold start

    def __init__(self, ctx):
        super().__init__(ctx)
        self.src = (
            pa_settings().nanoclaw_src or ctx.work_root / "nanoclaw-band"
        ).resolve()
        config_dir = self.workdir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.stack = ComposeStack(
            file=self.src / "docker-compose.yml",
            project=f"pa-nanoclaw-{ctx.run_id}",
            env={
                "NANOCLAW_HOST_PATH": str(self.src),
                "NANOCLAW_CONFIG_DIR": str(config_dir),
                "DOCKER_GID": str(os.stat("/var/run/docker.sock").st_gid),
                "COMPOSE_ONECLI_IMAGE": pa_settings().compose_onecli_image,
                "COMPOSE_CONTAINER_IMAGE": f"{_agent_image_base(self.src)}:latest",
                "COMPOSE_POSTGRES_PASSWORD": secrets.token_hex(16),
                **ctx.llm_env,
            },
        )

    def up(self, identity: BandIdentity) -> None:
        if not (self.src / "docker-compose.yml").exists():
            raise FileNotFoundError(
                f"no prepared NanoClaw checkout at {self.src} — run "
                "pa-conformance/stacks/nanoclaw/prepare.sh (NANOCLAW_SRC) first"
            )
        self.stack.redactions.add(identity.api_key)  # scrub it from logs()
        self._merge_env_file(
            BAND_AGENT_ID=identity.agent_id,
            BAND_AGENT_API_KEY=identity.api_key,
            BAND_BASE_URL=self.ctx.band_base_url,
            # Pass the agent key directly into agent containers in addition to
            # the vault route below. The localhost-only direct injection does
            # not apply to hosted Band.
            BAND_INJECT_API_KEY="true",
        )
        self.stack.up()
        self._seed_onecli_vault(identity)

    def _seed_onecli_vault(self, identity: BandIdentity) -> None:
        """Give agent containers their outbound credentials via OneCLI's
        secret-injection vault (containers never hold raw keys):

          - the Band agent key, injected as X-API-Key on egress to the
            configured Band host.
          - the Anthropic key for the Claude agent loop. NanoClaw reads it from
            the OneCLI vault, not from ANTHROPIC_API_KEY.

        Local gateway mode is authless; `--type` is required, and `generic`
        enables header injection.
        """
        band_host = urlparse(self.ctx.band_base_url).hostname or ""
        self._onecli(
            "secrets", "create",
            "--name", "Band",
            "--type", "generic",
            "--host-pattern", band_host,
            "--header-name", "X-API-Key",
            "--value", identity.api_key,
        )
        if anthropic_key := self.ctx.llm_env.get("ANTHROPIC_API_KEY"):
            self._onecli(
                "secrets", "create",
                "--name", "Anthropic",
                "--type", "anthropic",
                "--host-pattern", "api.anthropic.com",
                "--value", anthropic_key,
            )

    def wait_ready(self) -> None:
        wait_for(
            self._host_serving,
            timeout_s=self.ready_timeout_s,
            desc=f"nanoclaw host CLI socket ({self.stack.project})",
        )

    def _host_serving(self) -> bool:
        return self._ncl("users", "list", check=False).returncode == 0

    def attach_room(self, room_id: str) -> None:
        """Wire a Band room as a NanoClaw messaging group that can reply."""
        slug = f"pa-{room_id.split('-')[0]}"
        self.stack.exec(
            "nanoclaw",
            "pnpm", "exec", "tsx", "setup/index.ts", "--step", "register", "--",
            "--platform-id", f"band:{room_id}",
            "--name", slug,
            "--folder", slug,
            "--channel", "band",
            "--session-mode", "shared",
            "--assistant-name", slug,
        )
        group_id = self._sql_value(
            "SELECT id FROM messaging_groups WHERE platform_id = "
            f"'band:{room_id}'"
        )
        agent_group_id = self._sql_value(
            f"SELECT agent_group_id FROM messaging_group_agents "
            f"WHERE messaging_group_id = '{group_id}'"
        )
        self._ncl(
            "destinations", "add",
            "--agent-group-id", agent_group_id,
            "--local-name", slug,
            "--target-type", "channel",
            "--target-id", group_id,
        )
        self._ncl("groups", "restart", "--id", agent_group_id)

    def down(self) -> None:
        self.stack.down()
        # The host spawns per-agent sibling containers through the Docker
        # socket, outside compose. Sweep this checkout's agent image.
        ids = subprocess.run(
            ["docker", "ps", "-aq", "--filter",
             f"ancestor={_agent_image_base(self.src)}:latest"],
            capture_output=True, text=True,
        ).stdout.split()
        if ids:
            subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, text=True)

    def diagnostics(self) -> str:
        return (
            f"{super().diagnostics()} src={self.src}\n"
            f"{self.stack.ps()}\n{self.stack.logs('nanoclaw', 'onecli')}\n"
            f"{self._sibling_diagnostics()}"
        )

    def _sibling_diagnostics(self) -> str:
        """State + logs of the per-agent sibling containers the host spawns
        through the Docker socket — they live outside compose, so the stack's
        own ps/logs never show them, yet they run the actual agent loop."""
        ps = subprocess.run(
            ["docker", "ps", "-a", "--filter",
             f"ancestor={_agent_image_base(self.src)}:latest",
             "--format", "{{.ID}} {{.Status}} {{.Names}}"],
            capture_output=True, text=True,
        ).stdout.strip()
        report = [f"agent sibling containers:\n{ps or '(none)'}"]
        for container_id in (line.split()[0] for line in ps.splitlines() if line):
            logs = subprocess.run(
                ["docker", "logs", "--tail", "200", container_id],
                capture_output=True, text=True,
            )
            text = logs.stdout + logs.stderr
            for secret in self.stack.redactions:
                text = text.replace(secret, "***")
            report.append(f"--- agent container {container_id} ---\n{text}")
        return "\n".join(report)

    def _ncl(self, *argv: str, check: bool = True):
        return self.stack.exec("nanoclaw", *_NCL, *argv, check=check)

    def _onecli(self, *argv: str) -> subprocess.CompletedProcess[str]:
        """Run the pinned host-side onecli CLI (fetched by prepare.sh — the
        binary ships in neither compose image) against the stack's gateway.
        Local mode is authless; ONECLI_API_HOST scopes the call to this stack
        without touching the user's global CLI config."""
        cli = self.src / ".pa" / "onecli"
        port = pa_settings().compose_onecli_dashboard_port
        result = subprocess.run(
            [str(cli), *argv],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "ONECLI_API_HOST": f"http://127.0.0.1:{port}"},
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"onecli {argv[0]} {argv[1]} failed: {result.stdout}{result.stderr}"
            )
        return result

    def _sql_value(self, query: str) -> str:
        """Single-value query via scripts/q.ts, which prints sqlite3 "list"
        format: one row per line, pipe-separated, no header."""
        result = self.stack.exec("nanoclaw", *_Q, query)
        lines = result.stdout.strip().splitlines()
        assert lines, f"query returned no rows: {query}"
        return lines[0].split("|")[0]

    def _merge_env_file(self, **values: str) -> None:
        """Upsert KEY=VALUE lines into the checkout's .env."""
        env_file = self.src / ".env"
        lines = env_file.read_text().splitlines() if env_file.exists() else []
        keep = [
            line
            for line in lines
            if line.split("=", 1)[0].strip() not in values
        ]
        keep += [f"{key}={value}" for key, value in values.items()]
        env_file.write_text("\n".join(keep) + "\n")
