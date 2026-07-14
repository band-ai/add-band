"""Suite-wide settings for pa-conformance.

Mirrors the SDK toolkit's BaselineSettings idiom: pydantic-settings, env,
.env.test, and defaults that never raise. This module stays dependency-light
because driver/sdk.py needs `band_sdk_path` before the toolkit is importable.

Band credentials/endpoints stay in the SDK's BaselineSettings; this covers only
what the suite adds.
"""

from __future__ import annotations

import enum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_SUITE_ROOT = Path(__file__).resolve().parent

# Make add-band/.env.test visible to everything downstream (including the
# SDK's BaselineSettings, which reads os.environ first) regardless of CWD —
# the same import-time pattern the SDK uses for its own repo-root .env.test.
load_dotenv(_SUITE_ROOT.parent / ".env.test", override=False)

# pins.env carries the upstream component pins (single source of truth,
# Renovate-maintained). Loaded after .env.test with override=False, so the
# precedence is: process env > .env.test > pins.env.
load_dotenv(_SUITE_ROOT / "pins.env", override=False)


class ModelMode(str, enum.Enum):
    """How the model stand-in answers requests in a hosted test lane."""

    STRICT = "strict"
    PASSTHROUGH = "passthrough"


class TestLane(str, enum.Enum):
    """The hosted test class selected for this pytest process."""

    INTEGRATION = "integration"
    E2E = "e2e"


class PASettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    #: Same gate as the SDK suite: this suite is live-only by definition.
    e2e_tests_enabled: bool = False

    #: One hosted lane runs per pytest process because harnesses are
    #: session-scoped and each stack has one model stand-in configuration.
    pa_test_lane: TestLane = TestLane.E2E

    #: `strict` serves registered decisions only and never contacts a model
    #: provider. `passthrough` preserves the live-model E2E path.
    pa_model_mode: ModelMode = ModelMode.PASSTHROUGH

    #: Harness subset to run, comma-separated (PA_HARNESSES=hermes,openclaw).
    #: Empty means "all registered" — resolved where the registry is known,
    #: so this module never imports harness/.
    pa_harnesses: Annotated[tuple[str, ...], NoDecode] = ()

    #: Model stand-in kill switch (PA_STANDIN=off): stacks come up without the
    #: standin service and reach the model directly at api.anthropic.com;
    #: PA.model access skips. An operational escape hatch only — never a
    #: conformance state: Profile model_wire verdicts are untouched.
    pa_standin: bool = True

    #: Prepared NanoClaw checkout (stacks/nanoclaw/prepare.sh). Unset falls
    #: back to the run's work root.
    nanoclaw_src: Path | None = None

    #: OneCLI gateway image — the pin from nanoclaw-band's
    #: versions.json (`onecli-gateway`); the compose file refuses `latest`.
    compose_onecli_image: str = "ghcr.io/onecli/onecli:1.36.0"

    #: OpenClaw Band channel plugin version (npm). Pinned so an unversioned
    #: install can't pull a different (mutable `latest`) build between runs.
    #: The value comes from pins.env; required on purpose so the pin registry
    #: stays the single source of truth.
    openclaw_channel_version: str

    #: band-ai/hermes-band-platform commit baked into the Hermes image
    #: (compose build arg). The value comes from pins.env.
    band_hermes_ref: str

    #: Host port the OneCLI dashboard/API is published on (compose default).
    compose_onecli_dashboard_port: int = 10254

    #: Explicit band-sdk-python checkout (for hacking on suite + SDK
    #: together). Unset, driver/sdk.py auto-clones the toolkit tree into
    #: .deps/ at the exact commit the installed band-sdk came from.
    band_sdk_path: Path | None = None

    @field_validator("pa_harnesses", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(name.strip() for name in value.split(",") if name.strip())
        return value


@lru_cache(maxsize=1)
def pa_settings() -> PASettings:
    return PASettings()
