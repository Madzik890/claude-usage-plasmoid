#!/usr/bin/env python3
"""Fetch Claude subscription usage limits and print them as JSON.

Helper for the "Claude Usage" Plasma widget. Reads the OAuth token written by
Claude Code (read-only), queries the internal usage endpoint, caches the last
good result and sends desktop notifications when thresholds are crossed.
Always prints exactly one JSON object and exits with code 0.
"""

import argparse
import contextlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
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
SAME_WINDOW_S = 3600
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


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
    return "resets %s %d %s %s" % (WEEKDAYS[local.weekday()], local.day,
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
        # Grace period: the API may keep reporting a window shortly after it ended.
        return record_ts + SAME_WINDOW_S > now
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


def _valid_record(record):
    return (isinstance(record, dict) and isinstance(record.get("id"), str)
            and isinstance(record.get("threshold"), int)
            and not isinstance(record.get("threshold"), bool))


def _notify_thresholds(limits, warn, crit, now, notify):
    state_path = os.path.join(cache_dir(), "state.json")
    state = read_json(state_path)
    sent = state.get("sent") if isinstance(state, dict) else None
    sent = [r for r in sent if _valid_record(r)] if isinstance(sent, list) else []
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
        try:
            _notify_thresholds(limits, warn, crit, now, notify)
        except Exception:  # alerts must never cost the widget its fresh data
            pass
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
