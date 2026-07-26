"""Import bridge to band-sdk-python's baseline E2E toolkit.

The toolkit (tests/e2e/baseline/toolkit/ + settings.py) is pytest-free and
designed for reuse, but its modules import each other by the absolute dotted
path ``tests.e2e.baseline...``, so a checkout root must be on sys.path.
``driver.checkout`` acquires that checkout; this module puts it on sys.path
and re-exports the primitives the PA driver uses. Nothing else in
pa-conformance touches sys.path or the ``tests.e2e...`` namespace.
"""

from __future__ import annotations

import sys
from contextlib import AbstractAsyncContextManager
from typing import Callable

from driver.checkout import toolkit_checkout

BAND_SDK_PATH = toolkit_checkout()

if str(BAND_SDK_PATH) not in sys.path:
    sys.path.insert(0, str(BAND_SDK_PATH))

from tests.e2e.baseline.settings import BaselineSettings  # noqa: E402
from tests.e2e.baseline.toolkit.capture import (  # noqa: E402
    ReplyCapture,
    reply_capture,
)
from tests.e2e.baseline.toolkit.observations import Replies  # noqa: E402
from tests.e2e.baseline.toolkit.provisioning import (  # noqa: E402
    ProvisionedAgent,
    ResourceManager,
    agent_rest_client,
    new_run_id,
)
from tests.e2e.baseline.toolkit.user_ops import UserOps  # noqa: E402
from tests.e2e.helpers import TrackingWebSocketClient  # noqa: E402

from band.client.streaming import DeliveryStatus  # noqa: E402

#: A room-id-bound opener for ReplyCapture (what the `capture` fixture
#: yields). Defined here, not imported: it is a typing convenience only.
CaptureFactory = Callable[[str], AbstractAsyncContextManager[ReplyCapture]]

__all__ = [
    "BAND_SDK_PATH",
    "BaselineSettings",
    "CaptureFactory",
    "DeliveryStatus",
    "ProvisionedAgent",
    "Replies",
    "ReplyCapture",
    "ResourceManager",
    "TrackingWebSocketClient",
    "UserOps",
    "agent_rest_client",
    "new_run_id",
    "reply_capture",
]
