"""NanoClaw runner.

Unlike Hermes/OpenClaw there is no published image: stacks/nanoclaw/prepare.sh
must have materialized a Band-wired checkout (main + the band/adapter payload
+ pinned SDK deps) and built the host/agent images first — the runner points
at it via NANOCLAW_SRC and owns only runtime concerns.

Runtime shape:
  - the compose stack is postgres + onecli + the socket-mounted host, which
    spawns per-agent sibling containers through the Docker socket. DOCKER_GID
    is computed from that socket at runtime (DOCKER_HOST, else the conventional
    path), never hardcoded — it is host-specific by design.
  - identity is injected via the checkout's .env (BAND_AGENT_ID /
    BAND_AGENT_API_KEY), so no registration happens here.
  - NanoClaw routes per registered messaging group, so driver-created rooms
    must be wired in: attach_room() registers the room as an agent group
    (setup/index.ts --step register, which also wires the reply destination)
    and restarts the group.

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

from harness.compose import ComposeError, ComposeStack
from harness.contract import (
    STACKS_DIR,
    BandIdentity,
    Harness,
    ModelWire,
    Profile,
    Unknown,
    rewrite_env_value,
    wait_for,
)

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


def _docker_gid() -> int:
    """GID of the Docker socket, so the socket-mounted host can grant its
    sibling agent containers access to the daemon. Honors DOCKER_HOST
    (``unix://…``) and falls back to the conventional path; a socket that
    can't be reached is a clear setup error, not a bare stat traceback."""
    host = os.environ.get("DOCKER_HOST", "")
    socket = (
        Path(host[len("unix://") :])
        if host.startswith("unix://")
        else Path("/var/run/docker.sock")
    )
    try:
        return os.stat(socket).st_gid
    except OSError as exc:
        raise RuntimeError(
            f"Docker socket {socket} is unreachable ({exc.strerror}); NanoClaw "
            "mounts it to spawn agent containers — point DOCKER_HOST at a "
            "Unix socket (unix://…)"
        ) from exc


class NanoClawHarness(Harness):
    name = "nanoclaw"
    ready_timeout_s = 300.0  # postgres + onecli + host cold start
    #: Only the host is bounced: postgres and the onecli vault are the
    #: datastores rehydration reads from, so they stay up. Sibling agent
    #: containers live outside compose and are swept in stop().
    restart_services = ("nanoclaw",)
    profile = Profile(
        #: live wire 2026-07-12: mcp__nanoclaw__band_send_message et al.
        #: beside native SDK tools (Bash, Edit, …) and non-Band nanoclaw MCP
        #: tools (mcp__nanoclaw__send_message) in the recorded ModelCall.tools
        tool_namespace="mcp__nanoclaw__band_",
        #: live wire 2026-07-12: the Claude Agent SDK's shell tool, in
        #: ModelCall.tools (outside the Band namespace)
        native_tool="Bash",
        #: persisted `hub-room` state key + the `main room` row in v2.db
        #: (probed live 2026-07-12, L4 restart round)
        hub_identity="hub-room state key (main room row in v2.db)",
        #: attach_room registers a messaging group keyed `band:<room_id>` with
        #: session_mode=shared (setup/index.ts --step register; probed live
        #: 2026-07-12, L4 restart round)
        conversation_identity="messaging group per band:<room_id>, shared session",
        ordering_fallback=Unknown.UNKNOWN,
        idempotency_scheme=Unknown.UNKNOWN,
        #: live canary 2026-07-12: passthrough ModelCall recorded through the
        #: stand-in (upstream 200, vault auth injected en route via
        #: host-pattern `standin`) and a scripted decision served to the
        #: agent-loop call with the token echo landing on Band
        model_wire=ModelWire.SUPPORTED,
        band_context_read=Unknown.UNKNOWN,
        non_owner_policy=Unknown.UNKNOWN,
        #: live: test_restart's exactly-once row waits on PROCESSED and
        #: passes on NanoClaw (2026-07-12)
        emits_processed=True,
        #: live 2026-07-12 (L4 restart round): first connect creates the owner
        #: "Nano Hub" room; ensureOwnerHub is idempotent across restarts
        #: (persisted main-room state key)
        provisions_hub=True,
        rehydrates_thread_after_restart=Unknown.UNKNOWN,
    )

    def __init__(self, ctx):
        super().__init__(ctx)
        self.src = (
            pa_settings().nanoclaw_src or ctx.work_root / "nanoclaw-band"
        ).expanduser().resolve()
        config_dir = self.workdir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        # Identity is injected via a PER-RUN env file mounted over the host's
        # /app/.env (band-env.override.yaml) — never written into the shared
        # checkout, where credentials would outlive the run.
        self.band_env_file = self.workdir / "band.env"
        self._env_snapshot: str | None = None
        self._api_key: str | None = None
        # The per-agent image the host spawns siblings from; derived once and
        # reused for the compose env, the up() precondition, and teardown.
        self.agent_image = f"{_agent_image_base(self.src)}:latest"
        pg_password = secrets.token_hex(16)
        self.stack = ComposeStack(
            file=self.src / "docker-compose.yml",
            overrides=(
                STACKS_DIR / "nanoclaw" / "band-env.override.yaml",
                *self.standin_overrides(),
            ),
            project=f"pa-nanoclaw-{ctx.run_id}",
            env={
                "NANOCLAW_HOST_PATH": str(self.src),
                "NANOCLAW_CONFIG_DIR": str(config_dir),
                "PA_BAND_ENV_FILE": str(self.band_env_file),
                "DOCKER_GID": str(_docker_gid()),
                "COMPOSE_ONECLI_IMAGE": pa_settings().compose_onecli_image,
                "COMPOSE_CONTAINER_IMAGE": self.agent_image,
                "COMPOSE_POSTGRES_PASSWORD": pg_password,
                **ctx.llm_env,
                **self.standin_env(),
            },
        )
        # Everything secret that can reach an argv, a log line, or an error:
        # the generated DB password and the provider keys (the Anthropic key
        # rides `onecli secrets create --value …`). The agent key joins in
        # up(); the stand-in control token in up_standin() (base-owned).
        self.stack.redactions |= {pg_password, *ctx.llm_env.values()}

    def up(self, identity: BandIdentity) -> None:
        self._require_prepared()
        self._api_key = identity.api_key
        self.stack.redactions.add(identity.api_key)  # scrub it from logs()
        self.band_env_file.touch(mode=0o600)
        # ANTHROPIC_BASE_URL rides the per-run env file because that is the
        # upstream provider seam: src/providers/claude.ts reads it from
        # /app/.env and injects it (plus ANTHROPIC_AUTH_TOKEN=placeholder)
        # into every sibling agent container.
        standin_base_url = self.standin_env().get("ANTHROPIC_BASE_URL")
        self.band_env_file.write_text(
            f"BAND_AGENT_ID={identity.agent_id}\n"
            f"BAND_AGENT_API_KEY={identity.api_key}\n"
            f"BAND_BASE_URL={self.ctx.band_base_url}\n"
            # Pass the agent key directly into agent containers in addition to
            # the vault route below. The localhost-only direct injection does
            # not apply to hosted Band.
            "BAND_INJECT_API_KEY=true\n"
            + (f"ANTHROPIC_BASE_URL={standin_base_url}\n" if standin_base_url else "")
        )
        self.up_standin()
        self.stack.up()
        self._seed_onecli_vault(identity)

    def _require_prepared(self) -> None:
        """The prepared checkout must supply both the compose file and the
        slug-tagged agent image. The host spawns agents from that image at
        runtime, outside compose, where a missing tag surfaces only as an
        opaque 'agent never started' — so it is checked up front, here."""
        if not (self.src / "docker-compose.yml").exists():
            raise FileNotFoundError(
                f"no prepared NanoClaw checkout at {self.src} — run "
                "pa-conformance/stacks/nanoclaw/prepare.sh (NANOCLAW_SRC) first"
            )
        inspected = self.stack.run_local(
            ["docker", "image", "inspect", self.agent_image],
            check=False,
        )
        if inspected.returncode != 0:
            raise FileNotFoundError(
                f"NanoClaw agent image {self.agent_image} is missing — the "
                f"checkout at {self.src} was not built by its prepare.sh, or "
                "its path changed since (the tag is derived from the path)"
            )

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
            # With the stand-in in the model path, the secret's host-pattern
            # names the stand-in: sibling egress to it still rides the OneCLI
            # proxy (plain http included — an unmatched host gets a decorated
            # 401, observed live), so the key is injected en route and
            # forwarded upstream by the stand-in. Doctrine intact: sibling
            # containers never hold the raw key.
            self._onecli(
                "secrets", "create",
                "--name", "Anthropic",
                "--type", "anthropic",
                "--host-pattern",
                "standin" if self.standin_control_token else "api.anthropic.com",
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
        """Wire a Band room as a NanoClaw messaging group that can reply.

        The register step's wiring populates the reply `agent_destinations`
        row itself — a documented invariant (upstream docs/db-central.md §1.3:
        "creating a wiring must also populate agent_destinations"), and the
        pair is PK-unique, so adding it again here would fail."""
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
        self._ncl("groups", "restart", "--id", agent_group_id)

    def stop(self) -> None:
        """Halt the host, then sweep its sibling agent containers: a surviving
        sibling is an in-flight agent turn — in-memory carryover a faithful
        cold-start must not keep. Host first, so it cannot respawn a sibling
        mid-sweep; after start() the host re-wakes agents lazily on the next
        inbound message (container-runner wakeContainer), so nothing needs
        re-spawning here."""
        super().stop()
        if failures := self._sweep_siblings():
            raise RuntimeError("nanoclaw stop incomplete: " + "; ".join(failures))

    def corrupt_platform_creds(self) -> None:
        """The Band credential persists in TWO stores: band.env (the host's
        platform connection) and the OneCLI vault (X-API-Key egress injection
        for sibling agent containers). Both must go invalid — a healthy vault
        copy would let in-flight agent turns keep acting on Band while the
        host is degraded. The vault is mutable here because only the host is
        stopped; onecli stays up (it is not in restart_services)."""
        self._env_snapshot = rewrite_env_value(
            self.band_env_file, "BAND_AGENT_API_KEY", "pa-invalid-credential"
        )
        self._set_vault_band_secret("pa-invalid-credential")

    def restore_platform_creds(self) -> None:
        assert self._env_snapshot is not None, "corrupt_platform_creds() first"
        assert self._api_key is not None
        self.band_env_file.write_text(self._env_snapshot)
        self._env_snapshot = None
        self._set_vault_band_secret(self._api_key)

    def _set_vault_band_secret(self, value: str) -> None:
        """Repoint the vault's Band secret (seeded by _seed_onecli_vault).
        `--quiet <field>` prints one field per line, so two aligned lists
        beat parsing the CLI's table output."""
        ids = self._onecli("secrets", "list", "--quiet", "id")
        names = self._onecli("secrets", "list", "--quiet", "name")
        by_name = dict(zip(names.stdout.split(), ids.stdout.split()))
        self._onecli(
            "secrets", "update", "--id", by_name["Band"], "--value", value
        )

    def down(self) -> None:
        """Attempt every cleanup step; aggregate failures instead of masking
        them (a silently skipped `down -v` leaves secret-bearing volumes).
        Siblings are swept before `down` so failures there don't leave them
        running."""
        failures: list[str] = self._sweep_siblings()
        try:
            self.stack.down()
        except Exception as exc:
            failures.append(str(exc))
        if failures:
            raise RuntimeError(
                "nanoclaw teardown incomplete: " + "; ".join(failures)
            )

    def _sweep_siblings(self) -> list[str]:
        """Remove the per-agent sibling containers the host spawns through the
        Docker socket, outside compose, on the upstream's fixed
        `nanoclaw-compose` network. Swept by the checkout-derived agent image:
        install-scoped, not run-scoped — precise enough because two runs
        cannot share a checkout concurrently anyway (fixed network name +
        published OneCLI host port collide). Returns failure descriptions
        instead of raising so callers can aggregate."""
        try:
            ids_result = self.stack.run_local(
                ["docker", "ps", "-aq", "--filter", f"ancestor={self.agent_image}"],
                check=False,
            )
        except ComposeError as exc:
            return [f"sibling listing failed: {exc}"]
        if ids_result.returncode != 0:
            return [f"sibling listing failed: {ids_result.stderr.strip()}"]
        if ids := ids_result.stdout.split():
            try:
                removed = self.stack.run_local(
                    ["docker", "rm", "-f", *ids], check=False,
                )
            except ComposeError as exc:
                return [f"sibling removal failed: {exc}"]
            # Siblings are `docker run --rm` containers (upstream
            # container-runner.ts): when the host stops they exit and the
            # daemon's auto-remove reaps them, so `rm -f` racing that reaper
            # is the sweep succeeding, not failing.
            benign = ("already in progress", "No such container")
            errors = [
                line
                for line in removed.stderr.splitlines()
                if line.strip() and not any(b in line for b in benign)
            ]
            if removed.returncode != 0 and errors:
                return [f"sibling removal failed: {'; '.join(errors)}"]
        return []

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
        ps = self.stack.run_local(
            ["docker", "ps", "-a", "--filter", f"ancestor={self.agent_image}",
             "--format", "{{.ID}} {{.Status}} {{.Names}}"],
            check=False,
        ).stdout.strip()
        report = [f"agent sibling containers:\n{ps or '(none)'}"]
        for container_id in (line.split()[0] for line in ps.splitlines() if line):
            logs = self.stack.run_local(
                ["docker", "logs", "--tail", "200", container_id],
                check=False,
            )
            text = self.stack.scrub(logs.stdout + logs.stderr)
            report.append(f"--- agent container {container_id} ---\n{text}")
        return "\n".join(report)

    def _ncl(self, *argv: str, check: bool = True):
        return self.stack.exec("nanoclaw", *_NCL, *argv, check=check)

    def _onecli(self, *argv: str) -> subprocess.CompletedProcess[str]:
        """Run the pinned host-side onecli CLI (fetched by prepare.sh — the
        binary ships in neither compose image) against the stack's gateway.
        Local mode is authless; ONECLI_API_HOST scopes the call to this stack
        without touching the user's global CLI config.

        `secrets create --value <key>` puts secrets on this argv, so every
        surfaced failure — nonzero exit and timeout alike — goes through the
        stack's scrubber before it can reach a log or CI output.
        """
        cli = self.src / ".pa" / "onecli"
        port = pa_settings().compose_onecli_dashboard_port
        return self.stack.run_local(
            [str(cli), *argv],
            env={"ONECLI_API_HOST": f"http://127.0.0.1:{port}"},
            timeout_s=60,
        )

    def _sql_value(self, query: str) -> str:
        """Single-value query via scripts/q.ts, which prints sqlite3 "list"
        format: one row per line, pipe-separated, no header."""
        result = self.stack.exec("nanoclaw", *_Q, query)
        lines = result.stdout.strip().splitlines()
        assert lines, f"query returned no rows: {query}"
        return lines[0].split("|")[0]
