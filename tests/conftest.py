import sys
from pathlib import Path

# Make the project importable when running `pytest` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from citation_tracker import db
from citation_tracker.config import get_config


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """A fresh, isolated database for each test."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CITATION_DB_PATH", str(db_file))
    get_config.cache_clear()  # config is cached; reset for the new env
    db.init_db(db_file)
    yield db_file
    get_config.cache_clear()
