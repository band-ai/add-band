# Hermes gateway with the Band platform plugin baked in.
#
# Baked at build time because /opt/hermes is read-only for the runtime user.
# `uv pip install` targets the upstream image's venv; this directory is not a
# uv project.
#
# BAND_HERMES_REF selects the band-ai/hermes-band-platform git ref (the
# plugin has no PyPI release yet).
ARG HERMES_IMAGE=docker.io/nousresearch/hermes-agent:v2026.7.7.2
FROM ${HERMES_IMAGE}

ARG BAND_HERMES_REF=main
USER root
RUN uv pip install --python /opt/hermes/.venv/bin/python \
    "hermes-band-platform @ git+https://github.com/band-ai/hermes-band-platform.git@${BAND_HERMES_REF}"
