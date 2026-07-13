# Hermes gateway with the Band platform plugin baked in.
#
# Baked at build time because /opt/hermes is read-only for the runtime user.
# `uv pip install` targets the upstream image's venv; this directory is not a
# uv project.
#
# BAND_HERMES_REF selects the band-ai/hermes-band-platform commit (the plugin
# has no PyPI release yet). No default on purpose: the pin lives in
# pa-conformance/pins.env (single source of truth), and a moving-branch default
# would be irreproducible — and, as the only changing input to the RUN below,
# would let Docker reuse a stale cached layer after the branch moved.
ARG HERMES_IMAGE=docker.io/nousresearch/hermes-agent:v2026.7.7.2
FROM ${HERMES_IMAGE}

ARG BAND_HERMES_REF
USER root
RUN test -n "$BAND_HERMES_REF" \
    || { echo "BAND_HERMES_REF build arg is required (see pa-conformance/pins.env)" >&2; exit 1; } \
    && uv pip install --python /opt/hermes/.venv/bin/python \
    "hermes-band-platform @ git+https://github.com/band-ai/hermes-band-platform.git@${BAND_HERMES_REF}"
