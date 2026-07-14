"""A thin, uniform wrapper over `docker compose` for the harness runners.

Every stack is namespaced by compose project (`-p pa-<harness>-<run_id>`), so
three stacks coexist on one host and `down(volumes=True)` is a precise,
deterministic teardown — no reliance on auto-reapers (a fresh CI VM has
nothing to leak between runs; an `if: always()` down is the guarantee).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class ComposeError(RuntimeError):
    def __init__(self, cmd: str, stdout: str, stderr: str, returncode: int):
        super().__init__(
            f"`{cmd}` exited {returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )


@dataclass
class ComposeStack:
    file: Path
    project: str
    #: Compose override files, merged over `file` in order (`-f a -f b -f c`)
    #: — run-scoped adjustments layered on the base compose file: redirecting a
    #: bind-mount source to a per-run path, or adding the model stand-in
    #: service only when it is enabled (so PA_STANDIN=off means the service
    #: genuinely does not exist).
    overrides: tuple[Path, ...] = ()
    #: Extra env for every compose invocation (compose-file interpolation and
    #: `environment:` passthrough) — merged over the caller's environment.
    env: dict[str, str] = field(default_factory=dict)
    #: Secret values (agent keys, gateway tokens) scrubbed from any surfaced
    #: output — a failed config command can otherwise carry credentials on its
    #: argv straight into CI logs via the exception below.
    redactions: set[str] = field(default_factory=set)

    def scrub(self, text: str) -> str:
        """Blank every registered secret out of `text`. Public so runners can
        route their own subprocess output through the same redaction set."""
        for secret in self.redactions:
            if secret:
                text = text.replace(secret, "***")
        return text

    def _run(
        self, *args: str, check: bool = True, timeout_s: float = 600.0
    ) -> subprocess.CompletedProcess[str]:
        argv = ["docker", "compose", "-f", str(self.file)]
        for override in self.overrides:
            argv += ["-f", str(override)]
        argv += ["-p", self.project, *args]
        return self._run_command(argv, check=check, timeout_s=timeout_s)

    def _run_command(
        self,
        argv: list[str],
        *,
        check: bool = True,
        timeout_s: float = 120.0,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command and apply the stack's output-redaction policy."""
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env={**os.environ, **self.env, **(env or {})},
            )
        except subprocess.TimeoutExpired as exc:
            # Re-raise scrubbed: TimeoutExpired carries the raw argv (and any
            # partial output), which may hold secrets the redaction set covers.
            raise ComposeError(
                self.scrub(" ".join(argv)),
                self.scrub(str(exc.stdout or "")),
                self.scrub(str(exc.stderr or "")),
                returncode=-1,
            ) from None
        if check and result.returncode != 0:
            raise ComposeError(
                self.scrub(" ".join(argv)),
                self.scrub(result.stdout),
                self.scrub(result.stderr),
                result.returncode,
            )
        return result

    def run_local(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
        timeout_s: float = 120.0,
    ) -> subprocess.CompletedProcess[str]:
        """Run a host-side command with this stack's environment and scrubber."""
        return self._run_command(argv, check=check, timeout_s=timeout_s, env=env)

    def up(self, *services: str, build: bool = False) -> None:
        args = ["up", "-d", "--quiet-pull"]
        if build:
            args.append("--build")
        self._run(*args, *services)

    def down(self) -> None:
        """Full teardown: removes containers, networks, and volumes (`-v`);
        local images stay.

        Raises ComposeError on failure — a silently skipped `down -v` leaves
        containers and secret-bearing volumes behind; callers run teardown
        best-effort and are prepared to catch and log.
        """
        self._run("down", "-v", "--remove-orphans")

    def restart(self, *services: str) -> None:
        self._run("restart", *services)

    def stop(self, *services: str) -> None:
        """Halt containers without removing them: volumes, container config,
        and baked-in secrets stay intact, unlike `down`. With `start()` this
        is the only pair that yields a controllable down-window — `restart`
        offers no gap to act in while the service is stopped."""
        self._run("stop", *services)

    def start(self, *services: str) -> None:
        """Start containers previously halted by `stop()` — the same
        containers against their preserved state, nothing recreated.

        `up --no-recreate` rather than `compose start`: start re-resolves
        depends_on and refuses when a completed one-shot dependency's
        container is gone (NanoClaw's agent-build), while up reuses the
        existing stopped containers untouched. `--no-deps` needs an explicit
        service list; without one the whole stack comes up anyway."""
        args = ["up", "-d", "--no-recreate"]
        if services:
            args.append("--no-deps")
        self._run(*args, *services)

    def exec(
        self,
        service: str,
        *argv: str,
        user: str | None = None,
        check: bool = True,
        timeout_s: float = 120.0,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command in a RUNNING service container."""
        args = ["exec", "-T"]
        if user is not None:
            args += ["--user", user]
        return self._run(*args, service, *argv, check=check, timeout_s=timeout_s)

    def run(
        self,
        service: str,
        *argv: str,
        entrypoint: str | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
        timeout_s: float = 300.0,
    ) -> subprocess.CompletedProcess[str]:
        """One-shot `compose run --rm --no-deps` — for config commands that
        must not require (or start) the long-running services.

        `env` values land on the compose argv (`-e KEY=VAL`): secrets passed
        this way must be in `redactions`, which scrubs surfaced output — the
        value is still visible to `ps` on the host for the command's duration.
        """
        args = ["run", "--rm", "--no-deps", "-T"]
        for key, value in (env or {}).items():
            args += ["-e", f"{key}={value}"]
        if entrypoint is not None:
            args += ["--entrypoint", entrypoint]
        return self._run(*args, service, *argv, check=check, timeout_s=timeout_s)

    def port(self, service: str, container_port: int) -> int:
        """The host port published for `service`'s `container_port`.

        Dynamic publishing (`ports: - "8081"`) keeps parallel stacks from
        colliding on fixed host ports; this resolves what the daemon chose.
        """
        out = self._run("port", service, str(container_port)).stdout.strip()
        if not out:
            raise ComposeError(
                f"docker compose port {service} {container_port}",
                "", f"no published port for {service}:{container_port}", 1,
            )
        return int(out.splitlines()[0].rsplit(":", 1)[1])

    def logs(self, *services: str, tail: int = 200) -> str:
        result = self._run("logs", "--no-color", "--tail", str(tail), *services, check=False)
        return self.scrub(result.stdout + result.stderr)

    def ps(self) -> str:
        return self._run("ps", "-a", check=False).stdout
