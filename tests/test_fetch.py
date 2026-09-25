import urllib.error

import pytest

import claude_usage as cu
from conftest import NOW, write_credentials


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def reason_of(func, *args):
    with pytest.raises(cu.UsageError) as excinfo:
        func(*args)
    return excinfo.value.reason


def test_read_token_returns_access_token(tmp_path):
    path = tmp_path / "c.json"
    write_credentials(path, token="abc")
    assert cu.read_token(str(path), NOW) == "abc"


def test_read_token_missing_file(tmp_path):
    assert reason_of(cu.read_token, str(tmp_path / "none.json"), NOW) == "no_credentials"


def test_read_token_corrupt_file(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{not json")
    assert reason_of(cu.read_token, str(path), NOW) == "no_credentials"


def test_read_token_expired(tmp_path):
    path = tmp_path / "c.json"
    write_credentials(path, expires_at=NOW - 1)
    assert reason_of(cu.read_token, str(path), NOW) == "token_expired"


def test_normalize_uses_limits_array(usage_response):
    assert cu.normalize(usage_response) == [
        {"id": "session", "label": "Session (5h)", "percent": 22,
         "resets_at": "2026-09-25T13:39:59Z"},
        {"id": "weekly", "label": "Weekly", "percent": 10,
         "resets_at": "2026-09-26T01:59:59Z"},
        {"id": "weekly:Fable", "label": "Weekly · Fable", "percent": 0,
         "resets_at": "2026-09-26T02:00:00Z"},
    ]


def test_normalize_falls_back_to_legacy_fields(usage_response):
    del usage_response["limits"]
    assert cu.normalize(usage_response) == [
        {"id": "session", "label": "Session (5h)", "percent": 22,
         "resets_at": "2026-09-25T13:39:59Z"},
        {"id": "weekly", "label": "Weekly", "percent": 10,
         "resets_at": "2026-09-26T01:59:59Z"},
    ]


def test_normalize_skips_malformed_entries():
    data = {"limits": [
        {"kind": "session", "percent": "22"},
        {"kind": "weekly_all", "percent": 41.6, "resets_at": None},
        {"kind": "weekly_scoped", "percent": 5, "scope": "x"},
        {"kind": "weekly_scoped", "percent": 5, "resets_at": "garbage",
         "scope": {"model": {"display_name": "Opus"}}},
        {"kind": "unknown_future_kind", "percent": 1},
        "junk",
    ]}
    assert cu.normalize(data) == [
        {"id": "weekly", "label": "Weekly", "percent": 42, "resets_at": None},
        {"id": "weekly:Opus", "label": "Weekly · Opus", "percent": 5, "resets_at": None},
    ]


@pytest.mark.parametrize("data", [{}, {"limits": []}, [], {"five_hour": None}, None])
def test_normalize_without_any_limit_raises_parse(data):
    assert reason_of(cu.normalize, data) == "parse"


def test_fetch_usage_sends_token_and_parses(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["beta"] = request.get_header("Anthropic-beta")
        seen["timeout"] = timeout
        return FakeResponse(b'{"limits": []}')

    monkeypatch.setattr(cu.urllib.request, "urlopen", fake_urlopen)
    assert cu.fetch_usage("abc") == {"limits": []}
    assert seen == {"url": cu.USAGE_URL, "auth": "Bearer abc",
                    "beta": "oauth-2025-04-20", "timeout": cu.HTTP_TIMEOUT_S}


@pytest.mark.parametrize("error, reason", [
    (urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, None), "http_401"),
    (urllib.error.HTTPError("https://x", 500, "Server Error", {}, None), "http_500"),
    (urllib.error.URLError("down"), "network"),
    (TimeoutError(), "network"),
])
def test_fetch_usage_errors(monkeypatch, error, reason):
    def fake_urlopen(request, timeout):
        raise error

    monkeypatch.setattr(cu.urllib.request, "urlopen", fake_urlopen)
    assert reason_of(cu.fetch_usage, "abc") == reason


def test_fetch_usage_invalid_json(monkeypatch):
    monkeypatch.setattr(cu.urllib.request, "urlopen",
                        lambda request, timeout: FakeResponse(b"<html>"))
    assert reason_of(cu.fetch_usage, "abc") == "parse"
