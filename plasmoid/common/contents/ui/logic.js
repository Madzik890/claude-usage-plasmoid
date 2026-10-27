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
    return "resets " + WEEKDAYS[d.getDay()] + " " + d.getDate() + " " + MONTHS[d.getMonth()]
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
