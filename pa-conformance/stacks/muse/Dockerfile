FROM python:3.12-slim

RUN pip install --no-cache-dir band-sdk

# The bridge daemon from the Muse integration (muse/bridge_daemon.py)
COPY bridge_daemon.py /app/bridge_daemon.py

# Touch /tmp/bridge-ready when the WebSocket connects (readiness probe)
# The daemon writes this on successful RoomPresence.start()

WORKDIR /app
CMD ["python3", "bridge_daemon.py"]
