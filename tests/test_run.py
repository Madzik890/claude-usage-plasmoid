import json

import claude_usage as cu
from conftest import NOW, write_credentials


def cache_file(env, name):
    return env / "cache" / "claude-usage-widget" / name


def failing(reason):
    def fetch(token):
        raise cu.UsageError(reason)
    return fetch


def test_run_ok_writes_cache(env, usage_response):
    write_credentials(env / "credentials.json")
    result = cu.run(80, 95, False, now=NOW, fetch=lambda token: usage_response)
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["fetched_at"] == "2026-09-25T12:00:00Z"
    assert [l["id"] for l in result["limits"]] == ["session", "weekly", "weekly:Fable"]
    assert json.loads(cache_file(env, "last.json").read_text()) == result


def test_run_passes_token_to_fetch(env, usage_response):
    write_credentials(env / "credentials.json", token="secret")
    seen = []
    cu.run(80, 95, False, now=NOW, fetch=lambda token: seen.append(token) or usage_response)
    assert seen == ["secret"]


def test_run_expired_token_does_not_call_api(env):
    write_credentials(env / "credentials.json", expires_at=NOW - 60)

    def fetch(token):
        raise AssertionError("API must not be called")

    assert cu.run(80, 95, False, now=NOW, fetch=fetch) == {
        "status": "error", "reason": "token_expired", "fetched_at": None, "limits": []}


def test_run_error_returns_stale_cache(env, usage_response):
    write_credentials(env / "credentials.json")
    ok = cu.run(80, 95, False, now=NOW, fetch=lambda token: usage_response)
    stale = cu.run(80, 95, False, now=NOW + 300, fetch=failing("http_500"))
    assert stale == {"status": "stale", "reason": "http_500",
                     "fetched_at": "2026-09-25T12:00:00Z", "limits": ok["limits"]}


def test_run_corrupt_cache_is_ignored(env):
    write_credentials(env / "credentials.json")
    cache_file(env, "last.json").parent.mkdir(parents=True)
    cache_file(env, "last.json").write_text("{garbage")
    result = cu.run(80, 95, False, now=NOW, fetch=failing("network"))
    assert result["status"] == "error" and result["reason"] == "network"


def test_run_unwritable_cache_still_returns_ok(env, usage_response, monkeypatch):
    write_credentials(env / "credentials.json")

    def broken(path, obj):
        raise PermissionError(path)

    monkeypatch.setattr(cu, "write_json_atomic", broken)
    usage_response["limits"][0]["percent"] = 85
    notified = []
    result = cu.run(80, 95, True, now=NOW, fetch=lambda token: usage_response,
                    notify=lambda *args: notified.append(args))
    assert result["status"] == "ok"
    assert len(notified) == 1


def test_run_notifies_once_per_window(env, usage_response):
    write_credentials(env / "credentials.json")
    usage_response["limits"][0]["percent"] = 85
    notified = []

    def notify(limit, urgency, now):
        notified.append((limit["id"], urgency))

    cu.run(80, 95, True, now=NOW, fetch=lambda token: usage_response, notify=notify)
    cu.run(80, 95, True, now=NOW + 300, fetch=lambda token: usage_response, notify=notify)
    assert notified == [("session", "normal")]


def test_run_no_notify_flag(env, usage_response):
    write_credentials(env / "credentials.json")
    usage_response["limits"][0]["percent"] = 99

    def notify(*args):
        raise AssertionError("must not notify")

    assert cu.run(80, 95, False, now=NOW, fetch=lambda t: usage_response,
                  notify=notify)["status"] == "ok"


def test_run_does_not_notify_on_error(env):
    write_credentials(env / "credentials.json")

    def notify(*args):
        raise AssertionError("must not notify")

    cu.run(80, 95, True, now=NOW, fetch=failing("network"), notify=notify)


def test_run_corrupt_state_file_still_notifies(env, usage_response):
    write_credentials(env / "credentials.json")
    cache_file(env, "state.json").parent.mkdir(parents=True)
    cache_file(env, "state.json").write_text('{"sent": "nonsense"')
    usage_response["limits"][0]["percent"] = 85
    notified = []
    cu.run(80, 95, True, now=NOW, fetch=lambda t: usage_response,
           notify=lambda *args: notified.append(args))
    assert len(notified) == 1
    assert json.loads(cache_file(env, "state.json").read_text())["sent"][0]["id"] == "session"


def test_main_prints_json_and_exits_zero(env, capsys):
    assert cu.main(["--no-notify"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "error", "reason": "no_credentials", "fetched_at": None, "limits": []}


def test_main_reports_internal_error(env, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cu, "run", boom)
    assert cu.main([]) == 0
    assert json.loads(capsys.readouterr().out)["reason"] == "internal"


def test_main_outputs_utf8_characters(env, capsys, monkeypatch, usage_response):
    write_credentials(env / "credentials.json", expires_at=4102444800)
    monkeypatch.setattr(cu, "fetch_usage", lambda token: usage_response)
    assert cu.main(["--no-notify"]) == 0
    assert "Weekly ·" in capsys.readouterr().out


def test_run_state_with_wrong_types_still_returns_ok(env, usage_response):
    write_credentials(env / "credentials.json")
    cache_file(env, "state.json").parent.mkdir(parents=True)
    cache_file(env, "state.json").write_text(json.dumps({"sent": [
        {"id": "session", "threshold": None, "resets_at": None},
        {"id": "session", "threshold": "80", "resets_at": None}]}))
    usage_response["limits"][0]["percent"] = 85
    usage_response["limits"][0]["resets_at"] = None
    notified = []
    result = cu.run(80, 95, True, now=NOW, fetch=lambda t: usage_response,
                    notify=lambda *args: notified.append(args))
    assert result["status"] == "ok"
    assert len(notified) == 1
    assert json.loads(cache_file(env, "state.json").read_text())["sent"] == [
        {"id": "session", "threshold": 80, "resets_at": None}]


def test_run_returns_ok_when_notification_step_crashes(env, usage_response):
    write_credentials(env / "credentials.json")
    usage_response["limits"][0]["percent"] = 85

    def notify(*args):
        raise RuntimeError("notification backend exploded")

    assert cu.run(80, 95, True, now=NOW, fetch=lambda t: usage_response,
                  notify=notify)["status"] == "ok"
