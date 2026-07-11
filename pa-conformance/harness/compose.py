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
    #: Extra env for every compose invocation (compose-file interpolation and
    #: `environment:` passthrough) — merged over the caller's environment.
    env: dict[str, str] = field(default_factory=dict)
    #: Secret values (agent keys, gateway tokens) scrubbed from any surfaced
    #: output — a failed config command can otherwise carry credentials on its
    #: argv straight into CI logs via the exception below.
    redactions: set[str] = field(default_factory=set)

    def _scrub(self, text: str) -> str:
        for secret in self.redactions:
            if secret:
                text = text.replace(secret, "***")
        return text

    def _run(
        self, *args: str, check: bool = True, timeout_s: float = 600.0
    ) -> subprocess.CompletedProcess[str]:
        argv = ["docker", "compose", "-f", str(self.file), "-p", self.project, *args]
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, **self.env},
        )
        if check and result.returncode != 0:
            raise ComposeError(
                self._scrub(" ".join(argv)),
                self._scrub(result.stdout),
                self._scrub(result.stderr),
                result.returncode,
            )
        return result

    def up(self, *services: str, build: bool = False) -> None:
        args = ["up", "-d", "--quiet-pull"]
        if build:
            args.append("--build")
        self._run(*args, *services)

    def down(self) -> None:
        """Full teardown: containers, networks, volumes, local images stay."""
        self._run("down", "-v", "--remove-orphans", check=False)

    def restart(self, *services: str) -> None:
        self._run("restart", *services)

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
        check: bool = True,
        timeout_s: float = 300.0,
    ) -> subprocess.CompletedProcess[str]:
        """One-shot `compose run --rm --no-deps` — for config commands that
        must not require (or start) the long-running services."""
        args = ["run", "--rm", "--no-deps", "-T"]
        if entrypoint is not None:
            args += ["--entrypoint", entrypoint]
        return self._run(*args, service, *argv, check=check, timeout_s=timeout_s)

    def logs(self, *services: str, tail: int = 200) -> str:
        result = self._run("logs", "--no-color", "--tail", str(tail), *services, check=False)
        return self._scrub(result.stdout + result.stderr)

    def ps(self) -> str:
        return self._run("ps", "-a", check=False).stdout
