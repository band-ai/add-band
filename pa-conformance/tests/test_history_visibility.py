"""The mention-scoped context boundary matrix: reader × seed author × timing.

Band's design scopes an agent's context to its own conversation — what it
said and what was said to it; delivery is mention-only and rehydration
injects the same scope. Each cell plants one turn the reader was never
mentioned in and
asks the reader to echo it verbatim or declare blindness with a run-scoped
escape marker. A conformant reader declares blindness in every cell; a token
echo means a turn leaked across the boundary (the in-room counterpart of the
cross-room isolation scenario in test_memory). The reader's own reply is the
verdict, so a failing cell states the leak instead of leaving it to be
inferred.
"""

from __future__ import annotations

import pytest

from conftest import VisibilityProbe, selected_harnesses
from driver.visibility import Seed, SeedAuthor, Timing

CELLS = [
    Seed(author=SeedAuthor.USER, planted=Timing.LIVE),
    Seed(author=SeedAuthor.USER, planted=Timing.PRE_ATTACH),
    Seed(author=SeedAuthor.PEER, planted=Timing.LIVE),
    Seed(author=SeedAuthor.PEER, planted=Timing.PRE_ATTACH),
]


@pytest.mark.skipif(
    len(selected_harnesses()) < 2,
    reason="every cell seeds through a peer — needs a second harness",
)
@pytest.mark.parametrize("seed", CELLS, ids=str)
async def test_unaddressed_turns_stay_invisible(
    pa_name: str,
    seed: Seed,
    visibility_probe: VisibilityProbe,
) -> None:
    """A mentioned PA cannot read room turns that were never addressed to it."""
    outcome = await visibility_probe(reader=pa_name, seed=seed)
    outcome.assert_seed_invisible()
