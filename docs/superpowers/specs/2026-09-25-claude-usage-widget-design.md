# Claude Usage Widget — Design

Date: 2026-09-25

## Goal

Information always visible in the KDE Plasma panel showing how much of the
Claude subscription limit (Max plan) remains: the session limit (5 h window),
the weekly limit, and weekly per-model limits. A warning when approaching the
limit.

## Environment

- Ubuntu 22.04, KDE Plasma 5.24 (X11), Python 3.10, `notify-send`, `kpackagetool5`.
- No `plasmoidviewer` (package `plasma-sdk`) — UI testing happens by adding
  the widget to the panel.

## Data source (verified 2026-09-25)

- Token: `~/.claude/.credentials.json` → `claudeAiOauth.accessToken`,
  `claudeAiOauth.expiresAt` (ms since epoch).
- `GET https://api.anthropic.com/api/oauth/usage`
  headers: `Authorization: Bearer <token>`, `anthropic-beta: oauth-2025-04-20`.
- The response includes, among other things:
  - `limits[]`: `{kind, group, percent, severity, resets_at, scope, is_active}`;
    `kind` ∈ `session`, `weekly_all`, `weekly_scoped` (with `scope.model.display_name`).
  - legacy fields: `five_hour` / `seven_day` / `seven_day_opus` / `seven_day_sonnet`
    with `utilization` and `resets_at`.
- The endpoint is internal and undocumented — it may change. Unknown fields
  are ignored.

## Decisions

| Question | Decision |
|---|---|
| Form | Plasmoid (Plasma 5, QML) in the panel, popup with details |
| Logic | Helper in Python (stdlib, no dependencies), tested with pytest |
| Token | Read-only; the widget never modifies `.credentials.json` |
| Refresh | Every 5 min (configurable, minimum 2 min) + manually |
| Alerts | Colors (green < 70%, yellow 70–90%, red ≥ 90%) + `notify-send` at 80% and 95%, once per limit window |

## Architecture

```
helper/claude_usage.py         CLI: fetches, normalizes, caches, alerts → JSON on stdout
tests/test_claude_usage.py     pytest, no network
tests/fixtures/usage_response.json   anonymized real response
plasmoid/                      package com.github.madzik890.claudeusage
  metadata.json
  contents/config/main.xml     interval, thresholds
  contents/config/config.qml   config page registration
  contents/ui/main.qml         DataSource(executable), timer, state
  contents/ui/CompactRepresentation.qml
  contents/ui/FullRepresentation.qml
  contents/ui/configGeneral.qml
install.sh                     helper → ~/.local/bin/claude-usage, kpackagetool5 -i/-u
```

### Helper — CLI contract

`claude-usage [--warn 80] [--crit 95] [--no-notify]`

Always exit code 0 and a single JSON object on stdout:

```json
{
  "status": "ok | stale | error",
  "reason": null,
  "fetched_at": "2026-09-25T10:50:49+00:00",
  "limits": [
    {"id": "session", "label": "Session (5h)", "percent": 22,
     "resets_at": "2026-09-25T13:39:59+00:00"},
    {"id": "weekly", "label": "Weekly", "percent": 10, "resets_at": "..."},
    {"id": "weekly:Fable", "label": "Weekly · Fable", "percent": 0, "resets_at": "..."}
  ]
}
```

- `status=ok` — fresh data. `stale` — error, but the last cached data was
  returned (`fetched_at` from the cache). `error` — error and no cache
  (`limits: []`).
- `reason` ∈ `null`, `no_credentials`, `token_expired`, `http_401`, `http_<code>`,
  `network`, `parse`, `internal` (unexpected exception in the helper).
  The UI adds its own `helper` (the helper doesn't exist / returned invalid JSON).
- `resets_at` is normalized to `YYYY-MM-DDTHH:MM:SSZ` (UTC, without fractional
  seconds — the JS engine in Qt doesn't reliably parse 6-digit fractions) or
  `null`.
- Expired token (`expiresAt` < now) → the API is not called, `reason=token_expired`.

### Normalization

1. If `limits[]` exists: `session` → `session`; `weekly_all` → `weekly`;
   `weekly_scoped` → `weekly:<display_name>` (skipped when there is no name).
2. Otherwise fallback: `five_hour` → `session`, `seven_day` → `weekly`,
   `seven_day_opus`/`seven_day_sonnet` → `weekly:Opus`/`weekly:Sonnet`
   (`utilization` rounded to int), skipped when `null`.
3. No limit at all → `reason=parse`.

### Cache and state

- `~/.cache/claude-usage-widget/last.json` — the last successful result.
- `~/.cache/claude-usage-widget/state.json` — sent alerts:
  `{"sent": [{"id", "threshold", "resets_at"}]}`. An alert is considered sent
  when a record exists with the same `id` and threshold, and `resets_at`
  differing by less than 1 h (resilient to small fluctuations of `resets_at`
  between polls). Records with `resets_at` in the past are removed (alerts
  rearm after the window resets); records with `resets_at = null` live as
  long as the limit stays above the threshold.
- Atomic writes (temp file + `os.replace`).
- Directory overridable via `XDG_CACHE_HOME`; credentials path via the
  `CLAUDE_CREDENTIALS` variable (for tests).

### Alerts

Only when `status=ok`. For each limit and each threshold (`warn`, `crit`) that
`percent` has reached and that hasn't been sent yet in this window — one
notification per limit (for the highest newly crossed threshold): `notify-send`
(`-u critical` for `crit`, `-u normal` for `warn`, `-a "Claude Usage"`) with
content such as "Session (5h): 82% — resets in 1 h 12 min". A `notify-send`
error is ignored.

## UI

- Compact (panel): `S 22% · W 10%`, color based on the highest percentage
  (color thresholds 70/90 fixed in the UI, notification thresholds from the
  configuration). Grayed out on `stale`/`error`; on `error` with no data:
  `Claude ?`.
- Tooltip: the same shorthand + update time.
- Popup: for each limit a label, a progress bar, percentage, "resets in 1 h 12 min"
  (< 24 h) or "resets <weekday> HH:MM" (local time); footer: "Updated: HH:MM",
  the error message text in English, a "Refresh" button.
- Left-click opens the popup.
- Configuration: interval (min, 2–60, default 5), warning threshold (default 80),
  critical threshold (default 95).

Error messages:

| reason | Text |
|---|---|
| no_credentials | Not logged in — run `claude` and sign in |
| token_expired | Token expired — run Claude Code to refresh it |
| http_401 | Token rejected — run Claude Code |
| network | Cannot reach the API |
| helper | Helper unavailable — run install.sh |
| parse / http_* / internal | Unexpected API response |

When the helper fails (`helper`), the UI keeps the last displayed data marked
as stale instead of clearing it. The helper is invoked via the absolute path
`"$HOME/.local/bin/claude-usage"` (plasmashell's PATH may not include `~/.local/bin`).

## Testing

- pytest (no network, HTTP mocked by swapping out the fetch function):
  normalization from the fixture, fallback to legacy fields, no limits → parse,
  missing file, expired token (API not called), 401/500/network → stale from
  cache / error without cache, cache write, alert deduplication, rearming
  after a `resets_at` change, `--no-notify`.
- Manually: `claude-usage` live; widget added to the panel, checking the
  popup, the button, the color, the tooltip.

## Out of scope

- OAuth token refresh, Plasma 6 support, other desktop environments, history/charts.
