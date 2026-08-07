"""
Shared test setup.

The only thing here is a guard against the local GOL leaking into tests.
`osmsource.gol_path()` defaults to `data/hillbomb.gol` so that dev servers and
the collections builder pick it up with no configuration — which means that on a
machine where someone has built one, every test touching the search path would
silently change source depending on whether that file happens to exist. Tests
must not depend on the developer's data directory, so the default is switched off
for the whole suite and the tests that want a GOL opt in via the `real_gol`
fixture.
"""

import os

import pytest

# Captured at import, before any test can blank it. The integration test that
# diffs the two sources needs the value the developer actually passed.
_ENV_GOL = os.environ.get("HILLBOMB_GOL")


@pytest.fixture(autouse=True)
def no_ambient_gol(monkeypatch):
    # Empty (not unset) is the explicit "no local source" signal; unset would fall
    # back to the default path and reintroduce exactly the ambient dependency
    # this fixture exists to remove.
    monkeypatch.setenv("HILLBOMB_GOL", "")

    from .. import osmsource

    osmsource._manifest_cache.clear()
    osmsource._warned_missing.clear()
    yield
    osmsource._manifest_cache.clear()
    osmsource._warned_missing.clear()


@pytest.fixture
def real_gol():
    """The GOL path the developer passed in, or skip.

        HILLBOMB_GOL=data/hillbomb.gol pytest -m integration
    """
    if not _ENV_GOL or not os.path.exists(_ENV_GOL):
        pytest.skip("set HILLBOMB_GOL to a built .gol to run this")
    return _ENV_GOL
