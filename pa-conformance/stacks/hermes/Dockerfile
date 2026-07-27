# Hermes gateway with the Band platform plugin baked in.
#
# Baked at build time because /opt/hermes is read-only for the runtime user.
# `uv pip install` targets the upstream image's venv; this directory is not a
# uv project.
#
# Two pins select the plugin, both from pa-conformance/pins.env (single source
# of truth) and neither with a default: BAND_HERMES_VERSION is a PEP 440
# specifier for the released PyPI distribution and wins when set,
# BAND_HERMES_REF is the band-ai/hermes-band-platform commit used otherwise and
# as the fallback. A moving default on either would be irreproducible — and, as
# the only changing inputs to the RUN below, would let Docker reuse a stale
# cached layer after the branch or the release moved.
ARG HERMES_IMAGE
FROM ${HERMES_IMAGE}

ARG BAND_HERMES_REF
ARG BAND_HERMES_VERSION
USER root
# Prefer the pinned PyPI release, fall back to the pinned git ref if that
# install fails. BAND_HERMES_VERSION is appended to the name verbatim and so
# carries its own operator (`==1.2.3` pins one release; a range floats within
# it). It holds a pre-1.0 range in pins.env today, and `hermes-band` is not
# published yet, so that range resolves to nothing and the build still falls
# back to the git ref.
#
# Only `hermes-band` is ever requested from PyPI. The distribution was renamed
# hermes-band-platform -> hermes-band because the old name on PyPI belongs to an
# unrelated third party (INT-1137), and that placeholder ships an empty module
# under this plugin's exact import name — requesting the old name would install
# nothing useful and still build green.
#
# The git ref is installed as a bare URL, with no `NAME @ ` prefix: in a PEP 508
# direct reference pip and uv verify the built distribution's name against NAME,
# and that name is not stable across the refs this build must accept. Naming
# either side would pin the build to one side of the rename and fail on a
# BAND_HERMES_REF from the other, including a manual run that overrides the pin
# with an older ref.
#
# The entry-point check is what proves the real plugin landed, whichever source
# won. An import check would not — the placeholder owns that import name too.
RUN set -eu; \
    test -n "$BAND_HERMES_REF" \
      || { echo "BAND_HERMES_REF build arg is required (see pa-conformance/pins.env)" >&2; exit 1; }; \
    py=/opt/hermes/.venv/bin/python; \
    if [ -n "${BAND_HERMES_VERSION:-}" ] \
       && uv pip install --python "$py" "hermes-band${BAND_HERMES_VERSION}"; then \
      echo "band plugin: PyPI hermes-band${BAND_HERMES_VERSION}"; \
    else \
      [ -z "${BAND_HERMES_VERSION:-}" ] \
        || echo "band plugin: PyPI hermes-band${BAND_HERMES_VERSION} unavailable, falling back to git" >&2; \
      uv pip install --python "$py" \
        "git+https://github.com/band-ai/hermes-band-platform.git@${BAND_HERMES_REF}"; \
      echo "band plugin: git ${BAND_HERMES_REF}"; \
    fi; \
    "$py" -c "import importlib.metadata as m; assert any(e.name == 'band' for e in m.entry_points(group='hermes_agent.plugins')), 'no hermes_agent.plugins:band entry point — wrong distribution installed'"
