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
