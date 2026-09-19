import pytest

from app.throttle import _buckets
from app import main


@pytest.fixture(autouse=True)
def isolate_background_worker(monkeypatch):
    # TestClient lifespan must not settle real local accounts. Worker integration
    # tests invoke the real function explicitly with their test account scope.
    monkeypatch.setattr(main, 'settle_pending', lambda: None)
    monkeypatch.setattr(main, 'update_due', lambda: None)


@pytest.fixture(autouse=True)
def reset_throttle():
    """Keep each test's request budget independent without disabling throttling."""
    _buckets.clear()
    yield
    _buckets.clear()
