import json
import os
import sys
import time
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "helper"))

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def usage_response():
    with open(os.path.join(FIXTURES, "usage_response.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated credentials file and cache directory."""
    monkeypatch.setenv("CLAUDE_CREDENTIALS", str(tmp_path / "credentials.json"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path


@pytest.fixture
def utc_tz(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def write_credentials(path, token="tok", expires_at=NOW + 3600):
    path.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": token, "expiresAt": int(expires_at * 1000)}}))
