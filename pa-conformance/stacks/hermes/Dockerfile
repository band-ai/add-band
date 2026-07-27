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
ARG HERMES_IMAGE
FROM ${HERMES_IMAGE}

ARG BAND_HERMES_REF
USER root
# Installed as a bare git URL: no `NAME @ ` prefix. In a PEP 508 direct
# reference pip and uv verify the built distribution's name against NAME, and
# that name is not stable across the refs this build must accept — the repo
# renamed the distribution hermes-band-platform -> hermes-band (the old name
# on PyPI belongs to an unrelated third party). Naming either side here would
# pin the build to one side of that rename and fail on a BAND_HERMES_REF from
# the other, including a manual run that overrides the pin with an older ref.
# The URL already identifies the repo; the name only adds a thing a rename
# can break.
RUN test -n "$BAND_HERMES_REF" \
    || { echo "BAND_HERMES_REF build arg is required (see pa-conformance/pins.env)" >&2; exit 1; } \
    && uv pip install --python /opt/hermes/.venv/bin/python \
    "git+https://github.com/band-ai/hermes-band-platform.git@${BAND_HERMES_REF}"
