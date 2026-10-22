FROM python:3.12-slim

RUN pip install --no-cache-dir band-sdk

# Single source: the Muse integration's daemon. The build context is the
# repo root (see compose.yaml), so this COPYs muse/bridge_daemon.py itself —
# there is no second copy in the stack directory.
COPY muse/bridge_daemon.py /app/bridge_daemon.py

# Readiness: the daemon touches $BAND_BRIDGE_READY_FILE once the WebSocket
# connects; the compose healthcheck asserts that file exists.

WORKDIR /app
CMD ["python3", "bridge_daemon.py"]
