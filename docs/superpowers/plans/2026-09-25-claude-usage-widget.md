# Claude Usage Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A KDE Plasma 5 plasmoid in the panel showing the percentage usage of Claude subscription limits (5 h session, weekly, weekly per model), with colors and notifications at thresholds.

**Architecture:** A Python helper (`claude-usage`) reads the Claude Code token (read-only), queries `GET /api/oauth/usage`, normalizes the result, keeps a cache and alert state, sends `notify-send` notifications, and always prints a single JSON object. The QML plasmoid runs it every N minutes via the `executable` engine and only renders; the presentation logic lives in `logic.js` (tested with node).

**Tech Stack:** Python 3.10 (stdlib only), pytest 8, QML / Plasma 5.24 (`org.kde.plasma.core 2.0`, `org.kde.plasma.components 3.0`, `org.kde.plasma.extras 2.0`, Kirigami 2.5), node (only for `logic.js` tests), `kpackagetool5`, `plasmawindowed`.

**Spec:** `docs/superpowers/specs/2026-09-25-claude-usage-widget-design.md`

## Global Constraints

- Python: standard library only, compatible with Python 3.10.
- Never write to `~/.claude/.credentials.json` (read-only).
- The helper always exits with code 0 and prints exactly one JSON object `{status, reason, fetched_at, limits}`.
- `resets_at` / `fetched_at` in the format `YYYY-MM-DDTHH:MM:SSZ` or `null`.
- Refresh interval defaults to 5 min, range 2–60 min; notification thresholds default to 80 and 95.
- Colors: < 70% positive, 70–89% neutral, ≥ 90% negative (Plasma theme colors).
- UI texts in English.
- Package ID: `com.github.madzik890.claudeusage`; the helper is installed as `~/.local/bin/claude-usage`, invoked as `"$HOME/.local/bin/claude-usage"`.
- Git: `git add` only — **never `git commit`**; commits are the developer's responsibility.

## Review Focus

- `resets_at: null` or unparsable (the API returns `null` for some limits) → the limit is shown without reset text, alerts are deduplicated by `id` (tests: Task 1 `test_normalize_skips_malformed_entries`, Task 2 `test_limit_without_reset_time_alerts_once_and_rearms_after_drop`, Task 4 `formatReset(null)`).
- `resets_at` "drifts" slightly between polls → the same alert must not fire twice (Task 2 `test_small_resets_at_jitter_is_same_window`).
- Corrupted `last.json` / `state.json` (e.g. an interrupted write) → ignored, the helper keeps working (Task 3 `test_run_corrupt_cache_is_ignored`, `test_run_corrupt_state_file_still_notifies`).
- Cache directory not writable → `status: ok` with data is still returned (Task 3 `test_run_unwritable_cache_still_returns_ok`).
- Helper missing / outside plasmashell's PATH / printed garbage → "Helper unavailable" message, last data kept marked as stale (Task 4 `parseOutput`, `merge`).

---

## File Structure

```
helper/claude_usage.py              all of the helper's logic (CLI)
tests/conftest.py                   sys.path + fixtures
tests/fixtures/usage_response.json  anonymized real API response
tests/test_fetch.py                 Task 1
tests/test_alerts.py                Task 2
tests/test_run.py                   Task 3
tests/js/test_logic.js              Task 4
plasmoid/metadata.json
plasmoid/contents/config/main.xml
plasmoid/contents/config/config.qml
plasmoid/contents/ui/logic.js
plasmoid/contents/ui/main.qml
plasmoid/contents/ui/CompactRepresentation.qml
plasmoid/contents/ui/FullRepresentation.qml
plasmoid/contents/ui/configGeneral.qml
install.sh
```

---

### Task 1: Helper — token, fetching, normalization

**Files:**
- Create: `helper/claude_usage.py`
- Create: `tests/conftest.py`, `tests/fixtures/usage_response.json`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Produces:
  - `class UsageError(Exception)` with a `reason: str` attribute
  - `credentials_path() -> str`, `cache_dir() -> str`
  - `read_token(path: str, now: float) -> str` (raises `UsageError("no_credentials" | "token_expired")`)
  - `fetch_usage(token: str) -> object` (raises `UsageError("http_<code>" | "network" | "parse")`)
  - `parse_time(value) -> float | None`, `iso_utc(timestamp: float) -> str`
  - `normalize(data) -> list[dict]` — items `{"id", "label", "percent": int, "resets_at": str | None}`; raises `UsageError("parse")`
  - constants `USAGE_URL`, `HTTP_TIMEOUT_S`

- [ ] **Step 1: Test fixtures**

`tests/fixtures/usage_response.json`:

```json
{
  "five_hour": {"utilization": 22.0, "resets_at": "2026-09-25T13:39:59.901877+00:00"},
  "seven_day": {"utilization": 10.0, "resets_at": "2026-09-26T01:59:59.901899+00:00"},
  "seven_day_opus": null,
  "seven_day_sonnet": null,
  "limits": [
    {"kind": "session", "group": "session", "percent": 22, "severity": "normal",
     "resets_at": "2026-09-25T13:39:59.901877+00:00", "scope": null, "is_active": true},
    {"kind": "weekly_all", "group": "weekly", "percent": 10, "severity": "normal",
     "resets_at": "2026-09-26T01:59:59.901899+00:00", "scope": null, "is_active": false},
    {"kind": "weekly_scoped", "group": "weekly", "percent": 0, "severity": "normal",
     "resets_at": "2026-09-26T02:00:00+00:00",
     "scope": {"model": {"id": null, "display_name": "Fable"}, "surface": null},
     "is_active": false}
  ]
}
```

`tests/conftest.py`:

```python
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
```

- [ ] **Step 2: Write failing tests** — `tests/test_fetch.py`:

```python
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
    (urllib.error.HTTPError(cu.USAGE_URL, 401, "Unauthorized", {}, None), "http_401"),
    (urllib.error.HTTPError(cu.USAGE_URL, 500, "Server Error", {}, None), "http_500"),
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
```

- [ ] **Step 3: Run — expected FAIL**

Run: `python3 -m pytest tests/test_fetch.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'claude_usage'`

- [ ] **Step 4: Implementation** — `helper/claude_usage.py`:

```python
#!/usr/bin/env python3
"""Fetch Claude subscription usage limits and print them as JSON.

Helper for the "Claude Usage" Plasma widget. Reads the OAuth token written by
Claude Code (read-only), queries the internal usage endpoint, caches the last
good result and sends desktop notifications when thresholds are crossed.
Always prints exactly one JSON object and exits with code 0.
"""

import json
import math
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
HTTP_TIMEOUT_S = 10
LEGACY_FIELDS = (
    ("five_hour", "session", "Session (5h)"),
    ("seven_day", "weekly", "Weekly"),
    ("seven_day_opus", "weekly:Opus", "Weekly · Opus"),
    ("seven_day_sonnet", "weekly:Sonnet", "Weekly · Sonnet"),
)


class UsageError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def credentials_path():
    return os.environ.get("CLAUDE_CREDENTIALS") or os.path.expanduser(
        "~/.claude/.credentials.json")


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "claude-usage-widget")


def read_token(path, now):
    try:
        with open(path, encoding="utf-8") as f:
            oauth = json.load(f)["claudeAiOauth"]
        token = oauth["accessToken"]
    except (OSError, ValueError, KeyError, TypeError):
        raise UsageError("no_credentials") from None
    if not isinstance(token, str) or not token:
        raise UsageError("no_credentials")
    expires_at = oauth.get("expiresAt")
    if _is_number(expires_at) and expires_at / 1000 <= now:
        raise UsageError("token_expired")
    return token


def fetch_usage(token):
    request = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + token,
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
        "User-Agent": "claude-usage-widget/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            body = response.read()
    except urllib.error.HTTPError as e:
        raise UsageError("http_%d" % e.code) from None
    except (urllib.error.URLError, OSError):
        raise UsageError("network") from None
    try:
        return json.loads(body)
    except ValueError:
        raise UsageError("parse") from None


def parse_time(value):
    """Return a POSIX timestamp for an ISO 8601 string, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def iso_utc(timestamp):
    return datetime.fromtimestamp(int(timestamp), timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _limit(limit_id, label, percent, resets_at):
    ts = parse_time(resets_at)
    return {"id": limit_id, "label": label, "percent": int(round(percent)),
            "resets_at": iso_utc(ts) if ts is not None else None}


def _scope_model_name(item):
    scope = item.get("scope")
    model = scope.get("model") if isinstance(scope, dict) else None
    name = model.get("display_name") if isinstance(model, dict) else None
    return name if isinstance(name, str) and name else None


def normalize(data):
    if not isinstance(data, dict):
        raise UsageError("parse")
    limits = []
    items = data.get("limits")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not _is_number(item.get("percent")):
            continue
        kind = item.get("kind")
        if kind == "session":
            limits.append(_limit("session", "Session (5h)", item["percent"],
                                 item.get("resets_at")))
        elif kind == "weekly_all":
            limits.append(_limit("weekly", "Weekly", item["percent"],
                                 item.get("resets_at")))
        elif kind == "weekly_scoped":
            name = _scope_model_name(item)
            if name:
                limits.append(_limit("weekly:" + name, "Weekly · " + name,
                                     item["percent"], item.get("resets_at")))
    if not limits:
        for key, limit_id, label in LEGACY_FIELDS:
            item = data.get(key)
            if isinstance(item, dict) and _is_number(item.get("utilization")):
                limits.append(_limit(limit_id, label, item["utilization"],
                                     item.get("resets_at")))
    if not limits:
        raise UsageError("parse")
    return limits
```

- [ ] **Step 5: Run — expected PASS**

Run: `python3 -m pytest tests/test_fetch.py -q`
Expected: all tests PASS

- [ ] **Step 6: Stage (no commit)**

```bash
git add helper/claude_usage.py tests/conftest.py tests/fixtures/usage_response.json tests/test_fetch.py
```

---

### Task 2: Helper — alerts and notifications

**Files:**
- Modify: `helper/claude_usage.py` (add functions)
- Test: `tests/test_alerts.py`

**Interfaces:**
- Consumes: `parse_time` (Task 1)
- Produces:
  - `format_reset(resets_at: str | None, now: float) -> str` — `"resets in 1 h 12 min"`, `"resets in 30 min"`, `"resets soon"`, `"resets Sun 27 Sep 09:05"` (≥ 24 h, local time), `""` for `None`/garbage
  - `pending_alerts(limits, sent, warn, crit, now) -> (alerts, sent)`; `alerts: list[(limit_dict, "normal" | "critical")]`, `sent: list[{"id", "threshold", "resets_at"}]`
  - `send_notification(limit: dict, urgency: str, now: float) -> None`
  - constant `SAME_WINDOW_S = 3600`

- [ ] **Step 1: Write failing tests** — `tests/test_alerts.py`:

```python
import claude_usage as cu
from conftest import NOW

SESSION = {"id": "session", "label": "Session (5h)", "percent": 85,
           "resets_at": "2026-09-25T13:39:59Z"}


def lim(**overrides):
    limit = dict(SESSION)
    limit.update(overrides)
    return limit


def pending(limits, sent, now=NOW):
    return cu.pending_alerts(limits, sent, 80, 95, now)


def test_no_alert_below_threshold():
    assert pending([lim(percent=79)], []) == ([], [])


def test_warn_alert_is_sent_once():
    alerts, sent = pending([lim()], [])
    assert alerts == [(lim(), "normal")]
    assert sent == [{"id": "session", "threshold": 80,
                     "resets_at": "2026-09-25T13:39:59Z"}]
    alerts2, sent2 = pending([lim(percent=88)], sent, NOW + 300)
    assert alerts2 == []
    assert sent2 == sent


def test_crit_alert_after_warn():
    _, sent = pending([lim()], [])
    alerts, sent = pending([lim(percent=96)], sent)
    assert alerts == [(lim(percent=96), "critical")]
    assert sorted(r["threshold"] for r in sent) == [80, 95]


def test_jump_straight_to_crit_sends_single_critical():
    alerts, sent = pending([lim(percent=97)], [])
    assert alerts == [(lim(percent=97), "critical")]
    assert sorted(r["threshold"] for r in sent) == [80, 95]


def test_small_resets_at_jitter_is_same_window():
    _, sent = pending([lim()], [])
    alerts, _ = pending([lim(resets_at="2026-09-25T13:40:30Z")], sent)
    assert alerts == []


def test_new_window_rearms_alerts():
    _, sent = pending([lim()], [])
    new_window = lim(percent=81, resets_at="2026-09-25T18:39:59Z")
    alerts, sent2 = pending([new_window], sent, NOW + 2 * 3600)
    assert alerts == [(new_window, "normal")]
    assert sent2 == [{"id": "session", "threshold": 80,
                      "resets_at": "2026-09-25T18:39:59Z"}]


def test_limit_without_reset_time_alerts_once_and_rearms_after_drop():
    high = lim(resets_at=None)
    alerts, sent = pending([high], [])
    assert len(alerts) == 1
    alerts, sent = pending([high], sent)
    assert alerts == []
    alerts, sent = pending([lim(resets_at=None, percent=10)], sent)
    assert alerts == [] and sent == []
    alerts, _ = pending([high], sent)
    assert len(alerts) == 1


def test_limits_are_tracked_independently():
    weekly = {"id": "weekly", "label": "Weekly", "percent": 85,
              "resets_at": "2026-09-26T01:59:59Z"}
    alerts, _ = pending([lim(), weekly], [])
    assert alerts == [(lim(), "normal"), (weekly, "normal")]


def test_format_reset_relative():
    assert cu.format_reset("2026-09-25T13:12:00Z", NOW) == "resets in 1 h 12 min"
    assert cu.format_reset("2026-09-25T12:30:00Z", NOW) == "resets in 30 min"
    assert cu.format_reset("2026-09-25T11:00:00Z", NOW) == "resets soon"


def test_format_reset_invalid():
    assert cu.format_reset(None, NOW) == ""
    assert cu.format_reset("garbage", NOW) == ""


def test_format_reset_far_uses_local_date(utc_tz):
    assert cu.format_reset("2026-09-27T09:05:00Z", NOW) == "resets Sun 27 Sep 09:05"


def test_send_notification_calls_notify_send(monkeypatch):
    calls = []
    monkeypatch.setattr(cu.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    cu.send_notification(lim(), "critical", NOW)
    assert calls == [["notify-send", "-a", "Claude Usage", "-u", "critical",
                      "-i", "dialog-warning", "Claude: Session (5h) 85%",
                      "resets in 1 h 40 min"]]


def test_send_notification_ignores_missing_binary(monkeypatch):
    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(cu.subprocess, "run", missing)
    cu.send_notification(lim(), "normal", NOW)
```

- [ ] **Step 2: Run — expected FAIL**

Run: `python3 -m pytest tests/test_alerts.py -q`
Expected: FAIL with `AttributeError: module 'claude_usage' has no attribute 'pending_alerts'` (and similar)

- [ ] **Step 3: Implementation** — in `helper/claude_usage.py` add `import subprocess` to the imports, and constants below `LEGACY_FIELDS`:

```python
SAME_WINDOW_S = 3600
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
```

and functions at the end of the file:

```python
def format_reset(resets_at, now):
    ts = parse_time(resets_at)
    if ts is None:
        return ""
    minutes = round((ts - now) / 60)
    if minutes <= 0:
        return "resets soon"
    if minutes < 24 * 60:
        hours, mins = divmod(minutes, 60)
        return "resets in " + ("%d h " % hours if hours else "") + "%d min" % mins
    local = datetime.fromtimestamp(ts)
    return "resets %s %s %s %s" % (WEEKDAYS[local.weekday()], local.strftime("%d"),
                                   MONTHS[local.month - 1], local.strftime("%H:%M"))


def _already_sent(sent, limit, threshold):
    ts = parse_time(limit["resets_at"])
    for record in sent:
        if record.get("id") != limit["id"] or record.get("threshold") != threshold:
            continue
        record_ts = parse_time(record.get("resets_at"))
        if ts is None and record_ts is None:
            return True
        if ts is not None and record_ts is not None and abs(ts - record_ts) < SAME_WINDOW_S:
            return True
    return False


def _still_relevant(record, limits_by_id, now):
    record_ts = parse_time(record.get("resets_at"))
    if record_ts is not None:
        return record_ts > now
    limit = limits_by_id.get(record.get("id"))
    return (limit is not None and limit["resets_at"] is None
            and limit["percent"] >= record.get("threshold", 101))


def pending_alerts(limits, sent, warn, crit, now):
    """Decide which notifications to send.

    Returns (alerts, sent): alerts is a list of (limit, urgency), one per limit
    for its highest newly crossed threshold; sent is the updated list of
    {"id", "threshold", "resets_at"} records to persist.
    """
    alerts, new_records = [], []
    for limit in limits:
        fresh = [(threshold, urgency)
                 for threshold, urgency in ((warn, "normal"), (crit, "critical"))
                 if limit["percent"] >= threshold
                 and not _already_sent(sent, limit, threshold)]
        if fresh:
            alerts.append((limit, max(fresh, key=lambda item: item[0])[1]))
        new_records += [{"id": limit["id"], "threshold": threshold,
                         "resets_at": limit["resets_at"]} for threshold, _ in fresh]
    limits_by_id = {limit["id"]: limit for limit in limits}
    kept = [record for record in sent if _still_relevant(record, limits_by_id, now)]
    return alerts, kept + new_records


def send_notification(limit, urgency, now):
    title = "Claude: %s %d%%" % (limit["label"], limit["percent"])
    body = format_reset(limit["resets_at"], now)
    try:
        subprocess.run(["notify-send", "-a", "Claude Usage", "-u", urgency,
                        "-i", "dialog-warning", title, body],
                       check=False, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass
```

- [ ] **Step 4: Run — expected PASS**

Run: `python3 -m pytest tests -q`
Expected: all tests PASS

- [ ] **Step 5: Stage (no commit)**

```bash
git add helper/claude_usage.py tests/test_alerts.py
```

---

### Task 3: Helper — cache, `run()`, CLI

**Files:**
- Modify: `helper/claude_usage.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `read_token`, `fetch_usage`, `normalize`, `credentials_path`, `cache_dir`, `iso_utc` (Task 1); `pending_alerts`, `send_notification` (Task 2)
- Produces:
  - `read_json(path) -> object | None`, `write_json_atomic(path, obj) -> None`
  - `run(warn, crit, notify_enabled, now=None, fetch=None, notify=None) -> dict` (`fetch(token) -> object`, `notify(limit, urgency, now)`; `None` → `fetch_usage` / `send_notification` looked up at call time)
  - `main(argv=None) -> int` — CLI `claude-usage [--warn N] [--crit N] [--no-notify]`

- [ ] **Step 1: Write failing tests** — `tests/test_run.py`:

```python
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


def test_main_outputs_polish_characters(env, capsys, monkeypatch, usage_response):
    write_credentials(env / "credentials.json", expires_at=4102444800)
    monkeypatch.setattr(cu, "fetch_usage", lambda token: usage_response)
    assert cu.main(["--no-notify"]) == 0
    assert "Weekly" in capsys.readouterr().out
```

- [ ] **Step 2: Run — expected FAIL**

Run: `python3 -m pytest tests/test_run.py -q`
Expected: FAIL with `AttributeError: module 'claude_usage' has no attribute 'run'`

- [ ] **Step 3: Implementation** — in `helper/claude_usage.py` add `argparse`, `contextlib`, `sys`, `tempfile`, `time` to the imports, and at the end of the file:

```python
def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json_atomic(path, obj):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _notify_thresholds(limits, warn, crit, now, notify):
    state_path = os.path.join(cache_dir(), "state.json")
    state = read_json(state_path)
    sent = state.get("sent") if isinstance(state, dict) else None
    sent = [r for r in sent if isinstance(r, dict)] if isinstance(sent, list) else []
    alerts, sent = pending_alerts(limits, sent, warn, crit, now)
    for limit, urgency in alerts:
        notify(limit, urgency, now)
    with contextlib.suppress(OSError):
        write_json_atomic(state_path, {"sent": sent})


def run(warn, crit, notify_enabled, now=None, fetch=None, notify=None):
    now = time.time() if now is None else now
    fetch = fetch or fetch_usage
    notify = notify or send_notification
    last_path = os.path.join(cache_dir(), "last.json")
    try:
        limits = normalize(fetch(read_token(credentials_path(), now)))
    except UsageError as e:
        cached = read_json(last_path)
        if isinstance(cached, dict) and isinstance(cached.get("limits"), list) \
                and cached["limits"]:
            return {"status": "stale", "reason": e.reason,
                    "fetched_at": cached.get("fetched_at"), "limits": cached["limits"]}
        return {"status": "error", "reason": e.reason, "fetched_at": None, "limits": []}
    result = {"status": "ok", "reason": None, "fetched_at": iso_utc(now), "limits": limits}
    with contextlib.suppress(OSError):
        write_json_atomic(last_path, result)
    if notify_enabled:
        _notify_thresholds(limits, warn, crit, now, notify)
    return result


def _percent_arg(value):
    number = int(value)
    if not 1 <= number <= 100:
        raise argparse.ArgumentTypeError("value must be between 1 and 100")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Prints Claude subscription usage limits as JSON.")
    parser.add_argument("--warn", type=_percent_arg, default=80,
                        help="warning notification threshold in %% (default 80)")
    parser.add_argument("--crit", type=_percent_arg, default=95,
                        help="critical notification threshold in %% (default 95)")
    parser.add_argument("--no-notify", action="store_true",
                        help="do not send notifications")
    args = parser.parse_args(argv)
    try:
        result = run(args.warn, args.crit, not args.no_notify)
    except Exception:  # the widget must always receive valid JSON
        result = {"status": "error", "reason": "internal", "fetched_at": None, "limits": []}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run — expected PASS**

Run: `python3 -m pytest tests -q`
Expected: all tests PASS

- [ ] **Step 5: Live test (network, real token)**

Run: `XDG_CACHE_HOME=$(mktemp -d) python3 helper/claude_usage.py --no-notify`
Expected: `{"status": "ok", ...}` with limits `session`, `weekly`. If the API rejects the custom `User-Agent`, change it in `fetch_usage` and retry.

- [ ] **Step 6: Stage (no commit)**

```bash
chmod +x helper/claude_usage.py
git add helper/claude_usage.py tests/test_run.py
```

---

### Task 4: Plasmoid — presentation logic (`logic.js`)

**Files:**
- Create: `plasmoid/contents/ui/logic.js`
- Test: `tests/js/test_logic.js`

**Interfaces:**
- Consumes: the helper's JSON contract (Task 3)
- Produces (global functions of the `Logic` library in QML):
  - `level(percent) -> "ok" | "warn" | "crit"`
  - `maxPercent(limits) -> number` (`-1` when there is none)
  - `formatReset(iso, nowMs) -> string`, `formatTime(iso) -> "HH:MM" | "—"`
  - `errorText(reason) -> string`
  - `compactText(usage) -> string` (`"S 22% · W 10%"`, `"Claude …"`, `"Claude ?"`)
  - `tooltipText(usage, nowMs) -> string`
  - `parseOutput(exitCode, stdout) -> usage`
  - `merge(previous, next) -> usage`

- [ ] **Step 1: Write failing tests** — `tests/js/test_logic.js`:

```js
// Run with: TZ=UTC node tests/js/test_logic.js
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const source = fs
    .readFileSync(path.join(__dirname, "../../plasmoid/contents/ui/logic.js"), "utf8")
    .replace(/^\.pragma library\s*$/m, "");
const L = new Function(source + "\nreturn { level, maxPercent, formatReset, formatTime," +
    " errorText, compactText, tooltipText, parseOutput, merge };")();

const NOW = Date.parse("2026-09-25T12:00:00Z");
const USAGE = {
    status: "ok", reason: null, fetched_at: "2026-09-25T12:00:00Z",
    limits: [
        { id: "session", label: "Session (5h)", percent: 22, resets_at: "2026-09-25T13:12:00Z" },
        { id: "weekly", label: "Weekly", percent: 10, resets_at: "2026-09-27T09:05:00Z" },
        { id: "weekly:Fable", label: "Weekly · Fable", percent: 0, resets_at: null },
    ],
};
const tests = {
    level() {
        assert.strictEqual(L.level(69), "ok");
        assert.strictEqual(L.level(70), "warn");
        assert.strictEqual(L.level(89), "warn");
        assert.strictEqual(L.level(90), "crit");
    },
    maxPercent() {
        assert.strictEqual(L.maxPercent(USAGE.limits), 22);
        assert.strictEqual(L.maxPercent([]), -1);
        assert.strictEqual(L.maxPercent(undefined), -1);
    },
    formatReset() {
        assert.strictEqual(L.formatReset("2026-09-25T13:12:00Z", NOW), "resets in 1 h 12 min");
        assert.strictEqual(L.formatReset("2026-09-25T12:30:00Z", NOW), "resets in 30 min");
        assert.strictEqual(L.formatReset("2026-09-25T11:00:00Z", NOW), "resets soon");
        assert.strictEqual(L.formatReset("2026-09-27T09:05:00Z", NOW), "resets Sun 27 Sep 09:05");
        assert.strictEqual(L.formatReset(null, NOW), "");
        assert.strictEqual(L.formatReset("garbage", NOW), "");
    },
    formatTime() {
        assert.strictEqual(L.formatTime("2026-09-25T12:05:00Z"), "12:05");
        assert.strictEqual(L.formatTime(null), "—");
    },
    errorText() {
        assert.strictEqual(L.errorText("token_expired"),
            "Token expired — run Claude Code to refresh it");
        assert.strictEqual(L.errorText("helper"), "Helper unavailable — run install.sh");
        assert.strictEqual(L.errorText("http_503"), "Unexpected API response");
    },
    compactText() {
        assert.strictEqual(L.compactText(USAGE), "S 22% · W 10%");
        assert.strictEqual(L.compactText(null), "Claude …");
        assert.strictEqual(L.compactText({ status: "error", limits: [] }), "Claude ?");
        assert.strictEqual(L.compactText({ status: "ok", limits: [USAGE.limits[2]] }), "0%");
    },
    tooltipText() {
        assert.strictEqual(L.tooltipText(USAGE, NOW), [
            "Session (5h): 22% (resets in 1 h 12 min)",
            "Weekly: 10% (resets Sun 27 Sep 09:05)",
            "Weekly · Fable: 0%",
            "Updated: 12:00",
        ].join("\n"));
        const stale = Object.assign({}, USAGE, { status: "stale", reason: "network", limits: [] });
        assert.strictEqual(L.tooltipText(stale, NOW),
            "Cannot reach the API\nUpdated: 12:00");
        assert.strictEqual(L.tooltipText(null, NOW), "Loading…");
    },
    parseOutput() {
        assert.deepStrictEqual(L.parseOutput(0, JSON.stringify(USAGE)), USAGE);
        const helperError = { status: "error", reason: "helper", fetched_at: null, limits: [] };
        assert.deepStrictEqual(L.parseOutput(127, ""), helperError);
        assert.deepStrictEqual(L.parseOutput(0, "Traceback ..."), helperError);
        assert.deepStrictEqual(L.parseOutput(0, '{"status": "ok"}'), helperError);
    },
    merge() {
        const helperError = { status: "error", reason: "helper", fetched_at: null, limits: [] };
        assert.deepStrictEqual(L.merge(USAGE, helperError), {
            status: "stale", reason: "helper",
            fetched_at: USAGE.fetched_at, limits: USAGE.limits,
        });
        assert.deepStrictEqual(L.merge(null, helperError), helperError);
        const fresh = Object.assign({}, USAGE, { fetched_at: "2026-09-25T12:05:00Z" });
        assert.strictEqual(L.merge(USAGE, fresh), fresh);
    },
};

let failed = 0;
for (const [name, fn] of Object.entries(tests)) {
    try {
        fn();
        console.log("PASS " + name);
    } catch (e) {
        failed++;
        console.log("FAIL " + name + ": " + e.message);
    }
}
process.exit(failed ? 1 : 0);
```

- [ ] **Step 2: Run — expected FAIL**

Run: `TZ=UTC node tests/js/test_logic.js`
Expected: `ENOENT: no such file or directory ... logic.js`

- [ ] **Step 3: Implementation** — `plasmoid/contents/ui/logic.js`:

```js
.pragma library

var WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

var ERROR_TEXTS = {
    no_credentials: "Not logged in — run claude and sign in",
    token_expired: "Token expired — run Claude Code to refresh it",
    http_401: "Token rejected — run Claude Code",
    network: "Cannot reach the API",
    helper: "Helper unavailable — run install.sh"
};

function level(percent) {
    if (percent >= 90)
        return "crit";
    if (percent >= 70)
        return "warn";
    return "ok";
}

function maxPercent(limits) {
    var max = -1;
    (limits || []).forEach(function (limit) { max = Math.max(max, limit.percent); });
    return max;
}

function pad2(n) {
    return (n < 10 ? "0" : "") + n;
}

function formatReset(iso, nowMs) {
    var t = iso ? Date.parse(iso) : NaN;
    if (isNaN(t))
        return "";
    var minutes = Math.round((t - nowMs) / 60000);
    if (minutes <= 0)
        return "resets soon";
    if (minutes < 24 * 60) {
        var hours = Math.floor(minutes / 60);
        return "resets in " + (hours > 0 ? hours + " h " : "") + (minutes % 60) + " min";
    }
    var d = new Date(t);
    return "resets " + WEEKDAYS[d.getDay()] + " " + pad2(d.getDate()) + " " + MONTHS[d.getMonth()]
        + " " + pad2(d.getHours()) + ":" + pad2(d.getMinutes());
}

function formatTime(iso) {
    var t = iso ? Date.parse(iso) : NaN;
    if (isNaN(t))
        return "—";
    var d = new Date(t);
    return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
}

function errorText(reason) {
    return ERROR_TEXTS[reason] || "Unexpected API response";
}

function findLimit(limits, id) {
    for (var i = 0; i < limits.length; i++) {
        if (limits[i].id === id)
            return limits[i];
    }
    return null;
}

function compactText(usage) {
    if (!usage)
        return "Claude …";
    if (!usage.limits || usage.limits.length === 0)
        return "Claude ?";
    var parts = [];
    var session = findLimit(usage.limits, "session");
    var weekly = findLimit(usage.limits, "weekly");
    if (session)
        parts.push("S " + session.percent + "%");
    if (weekly)
        parts.push("W " + weekly.percent + "%");
    if (parts.length === 0)
        parts.push(usage.limits[0].percent + "%");
    return parts.join(" · ");
}

function tooltipText(usage, nowMs) {
    if (!usage)
        return "Loading…";
    var lines = [];
    (usage.limits || []).forEach(function (limit) {
        var reset = formatReset(limit.resets_at, nowMs);
        lines.push(limit.label + ": " + limit.percent + "%" + (reset ? " (" + reset + ")" : ""));
    });
    if (usage.status !== "ok")
        lines.push(errorText(usage.reason));
    lines.push("Updated: " + formatTime(usage.fetched_at));
    return lines.join("\n");
}

function parseOutput(exitCode, stdout) {
    if (Number(exitCode) === 0) {
        try {
            var usage = JSON.parse(stdout);
            if (usage && typeof usage.status === "string" && Array.isArray(usage.limits))
                return usage;
        } catch (e) {
            // fall through to the helper error below
        }
    }
    return { status: "error", reason: "helper", fetched_at: null, limits: [] };
}

function merge(previous, next) {
    if (next.status === "error" && previous && previous.limits && previous.limits.length > 0) {
        return { status: "stale", reason: next.reason,
                 fetched_at: previous.fetched_at, limits: previous.limits };
    }
    return next;
}
```

- [ ] **Step 4: Run — expected PASS**

Run: `TZ=UTC node tests/js/test_logic.js`
Expected: 9× `PASS`, exit 0

- [ ] **Step 5: Stage (no commit)**

```bash
git add plasmoid/contents/ui/logic.js tests/js/test_logic.js
```

---

### Task 5: Plasmoid — QML, configuration, installation

**Files:**
- Create: `plasmoid/metadata.json`, `plasmoid/contents/config/main.xml`, `plasmoid/contents/config/config.qml`
- Create: `plasmoid/contents/ui/main.qml`, `CompactRepresentation.qml`, `FullRepresentation.qml`, `configGeneral.qml`
- Create: `install.sh`

**Interfaces:**
- Consumes: `Logic.*` (Task 4); CLI `claude-usage --warn N --crit N` (Task 3)
- Produces: the `root` object (main.qml) passed as `backend` to the representations, with: `usage: var`, `nowMs: double`, `colorFor(percent) -> color`, `refresh()`

- [ ] **Step 1: Metadata and configuration**

`plasmoid/metadata.json`:

```json
{
    "KPlugin": {
        "Id": "com.github.madzik890.claudeusage",
        "Name": "Claude Usage",
        "Description": "Claude subscription usage limits",
        "Icon": "utilities-system-monitor",
        "Authors": [{ "Name": "Marcin Sucharski" }],
        "Category": "System Information",
        "License": "MIT",
        "Version": "1.0.0",
        "ServiceTypes": ["Plasma/Applet"]
    },
    "X-Plasma-API": "declarativeappletscript",
    "X-Plasma-MainScript": "ui/main.qml"
}
```

`plasmoid/contents/config/main.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<kcfg xmlns="http://www.kde.org/standards/kcfg/1.0"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:schemaLocation="http://www.kde.org/standards/kcfg/1.0 http://www.kde.org/standards/kcfg/1.0/kcfg.xsd">
    <kcfgfile name=""/>
    <group name="General">
        <entry name="refreshMinutes" type="Int">
            <default>5</default>
            <min>2</min>
            <max>60</max>
        </entry>
        <entry name="warnThreshold" type="Int">
            <default>80</default>
            <min>1</min>
            <max>100</max>
        </entry>
        <entry name="critThreshold" type="Int">
            <default>95</default>
            <min>1</min>
            <max>100</max>
        </entry>
    </group>
</kcfg>
```

`plasmoid/contents/config/config.qml`:

```qml
import QtQuick 2.15
import org.kde.plasma.configuration 2.0

ConfigModel {
    ConfigCategory {
        name: "General"
        icon: "configure"
        source: "configGeneral.qml"
    }
}
```

`plasmoid/contents/ui/configGeneral.qml`:

```qml
import QtQuick 2.15
import QtQuick.Controls 2.15 as QQC2
import org.kde.kirigami 2.5 as Kirigami

Kirigami.FormLayout {
    property alias cfg_refreshMinutes: refreshSpin.value
    property alias cfg_warnThreshold: warnSpin.value
    property alias cfg_critThreshold: critSpin.value

    QQC2.SpinBox {
        id: refreshSpin
        Kirigami.FormData.label: "Refresh interval (min):"
        from: 2
        to: 60
    }
    QQC2.SpinBox {
        id: warnSpin
        Kirigami.FormData.label: "Warning notification (%):"
        from: 1
        to: 100
    }
    QQC2.SpinBox {
        id: critSpin
        Kirigami.FormData.label: "Critical notification (%):"
        from: 1
        to: 100
    }
}
```

- [ ] **Step 2: `plasmoid/contents/ui/main.qml`**

```qml
import QtQuick 2.15
import org.kde.plasma.core 2.0 as PlasmaCore
import org.kde.plasma.plasmoid 2.0
import "logic.js" as Logic

Item {
    id: root

    property var usage: null
    property double nowMs: Date.now()
    readonly property string helperCommand: "\"$HOME/.local/bin/claude-usage\""
        + " --warn " + plasmoid.configuration.warnThreshold
        + " --crit " + plasmoid.configuration.critThreshold

    function colorFor(percent) {
        switch (Logic.level(percent)) {
        case "crit":
            return PlasmaCore.Theme.negativeTextColor;
        case "warn":
            return PlasmaCore.Theme.neutralTextColor;
        default:
            return PlasmaCore.Theme.positiveTextColor;
        }
    }

    function refresh() {
        if (executable.connectedSources.indexOf(helperCommand) === -1)
            executable.connectSource(helperCommand);
    }

    Plasmoid.icon: "utilities-system-monitor"
    Plasmoid.toolTipMainText: "Claude Usage"
    Plasmoid.toolTipSubText: Logic.tooltipText(usage, nowMs)
    Plasmoid.compactRepresentation: CompactRepresentation { backend: root }
    Plasmoid.fullRepresentation: FullRepresentation { backend: root }

    PlasmaCore.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []
        onNewData: {
            disconnectSource(sourceName);
            root.usage = Logic.merge(root.usage,
                                     Logic.parseOutput(data["exit code"], data["stdout"]));
            root.nowMs = Date.now();
        }
    }

    Timer {
        interval: Math.max(2, plasmoid.configuration.refreshMinutes) * 60 * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    Timer {
        interval: 30 * 1000
        running: true
        repeat: true
        onTriggered: root.nowMs = Date.now()
    }
}
```

- [ ] **Step 3: `plasmoid/contents/ui/CompactRepresentation.qml`**

```qml
import QtQuick 2.15
import QtQuick.Layouts 1.15
import org.kde.plasma.core 2.0 as PlasmaCore
import org.kde.plasma.components 3.0 as PlasmaComponents3
import org.kde.plasma.plasmoid 2.0
import "logic.js" as Logic

MouseArea {
    id: compact

    property var backend
    readonly property var usage: backend.usage
    readonly property bool hasLimits: usage !== null && usage.limits.length > 0

    Layout.minimumWidth: label.implicitWidth + PlasmaCore.Units.smallSpacing * 2
    Layout.preferredWidth: Layout.minimumWidth
    hoverEnabled: true
    onClicked: plasmoid.expanded = !plasmoid.expanded

    PlasmaComponents3.Label {
        id: label
        anchors.centerIn: parent
        text: Logic.compactText(compact.usage)
        font.bold: true
        color: compact.hasLimits ? compact.backend.colorFor(Logic.maxPercent(compact.usage.limits))
                                 : PlasmaCore.Theme.textColor
        opacity: compact.usage !== null && compact.usage.status === "ok" ? 1.0 : 0.5
    }
}
```

- [ ] **Step 4: `plasmoid/contents/ui/FullRepresentation.qml`**

```qml
import QtQuick 2.15
import QtQuick.Layouts 1.15
import org.kde.plasma.core 2.0 as PlasmaCore
import org.kde.plasma.components 3.0 as PlasmaComponents3
import org.kde.plasma.extras 2.0 as PlasmaExtras
import "logic.js" as Logic

Item {
    id: full

    property var backend
    readonly property var usage: backend.usage

    Layout.minimumWidth: PlasmaCore.Units.gridUnit * 18
    Layout.minimumHeight: column.implicitHeight + PlasmaCore.Units.smallSpacing * 2
    Layout.preferredWidth: Layout.minimumWidth
    Layout.preferredHeight: Layout.minimumHeight

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: PlasmaCore.Units.smallSpacing
        spacing: PlasmaCore.Units.smallSpacing

        PlasmaExtras.Heading {
            level: 4
            text: "Claude limits"
            Layout.fillWidth: true
        }

        Repeater {
            model: full.usage ? full.usage.limits : []

            delegate: ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                RowLayout {
                    Layout.fillWidth: true
                    PlasmaComponents3.Label {
                        text: modelData.label
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    PlasmaComponents3.Label {
                        text: modelData.percent + "%"
                        font.bold: true
                        color: full.backend.colorFor(modelData.percent)
                    }
                }
                PlasmaComponents3.ProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: 100
                    value: Math.min(100, Math.max(0, modelData.percent))
                }
                PlasmaComponents3.Label {
                    text: Logic.formatReset(modelData.resets_at, full.backend.nowMs)
                    visible: text !== ""
                    opacity: 0.7
                    font: PlasmaCore.Theme.smallestFont
                }
            }
        }

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            visible: text !== ""
            color: PlasmaCore.Theme.negativeTextColor
            text: full.usage === null ? "Loading…"
                : full.usage.status !== "ok" ? Logic.errorText(full.usage.reason) : ""
        }

        RowLayout {
            Layout.fillWidth: true
            PlasmaComponents3.Label {
                text: "Updated: " + Logic.formatTime(full.usage ? full.usage.fetched_at : null)
                opacity: 0.7
                Layout.fillWidth: true
            }
            PlasmaComponents3.ToolButton {
                icon.name: "view-refresh"
                text: "Refresh"
                onClicked: full.backend.refresh()
            }
        }
    }
}
```

- [ ] **Step 5: `install.sh`**

```bash
#!/usr/bin/env bash
# Installs the claude-usage helper and the Claude Usage plasmoid for the current user.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="com.github.madzik890.claudeusage"

install -D -m 0755 "$HERE/helper/claude_usage.py" "$HOME/.local/bin/claude-usage"
echo "Helper: $HOME/.local/bin/claude-usage"

if kpackagetool5 --type Plasma/Applet --list 2>/dev/null | grep -q "^$PLUGIN_ID\$"; then
    kpackagetool5 --type Plasma/Applet --upgrade "$HERE/plasmoid"
else
    kpackagetool5 --type Plasma/Applet --install "$HERE/plasmoid"
fi

cat <<EOF

Installed plasmoid $PLUGIN_ID.
- Preview in a window:  plasmawindowed $PLUGIN_ID
- Add to panel:         right-click the panel → Add Widgets… → "Claude Usage"
- After updating a widget already on the panel: plasmashell --replace &
EOF
```

- [ ] **Step 6: Lint QML**

Run: `qmllint plasmoid/contents/ui/*.qml plasmoid/contents/config/config.qml`
Expected: no syntax errors (warnings about unknown Plasma imports are acceptable)

- [ ] **Step 7: Installation and preview**

Run: `bash install.sh && plasmawindowed com.github.madzik890.claudeusage`
Expected: a window with the widget; text `S xx% · W yy%` in color; clicking opens the popup with bars, reset time and a "Refresh" button; no QML errors on stderr. Also check the error scenario: temporarily `mv ~/.local/bin/claude-usage{,.bak}` → after "Refresh" the message "Helper unavailable", data grayed out; restore the file.

- [ ] **Step 8: Stage (no commit)**

```bash
chmod +x install.sh
git add plasmoid install.sh
```

- [ ] **Step 9: Add to the panel (manually, by the user)**

Right-click the panel → "Add Widgets…" → "Claude Usage" → drag onto the panel.
