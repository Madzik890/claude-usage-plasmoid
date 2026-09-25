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
    _, sent3 = pending([new_window], sent2, NOW + 3 * 3600)
    assert sent3 == [{"id": "session", "threshold": 80,
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


def test_past_resets_at_does_not_realert_every_other_poll():
    lagging = lim(resets_at="2026-09-25T11:59:00Z")
    sent, counts = [], []
    for i in range(5):
        alerts, sent = pending([lagging], sent, NOW + i * 300)
        counts.append(len(alerts))
    assert counts == [1, 0, 0, 0, 0]
