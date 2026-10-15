// Technical HTTP acceptance using the actual clients and one scheduler per tab.
// Does not open or automate a browser or read a user's stored credentials.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { AsyncLocalStorage } from "node:async_hooks";
const require = createRequire(new URL("../../../wealth/package.json", import.meta.url));
const { build } = require("esbuild");
const root = fileURLToPath(new URL("../../../", import.meta.url));
const [base, output] = process.argv.slice(2);
assert(base && output);
const prefix = `${root}wealth/src/features/index-detail/`;
const entry = [
  ["api/indexDetailApiClient.ts", "fetchIndexDetailMinutes, fetchIndexDetailMinuteIndicators, fetchIndexDetailKline"],
  ["api/indexNineTurnLoader.ts", "loadIndexNineTurnSeries"],
  ["api/indexDetailRequestScheduler.ts", "indexDetailRequests"],
  ["xxm/apiClient.ts", "fetchXxm"], ["xxm-forecast/apiClient.ts", "fetchForecast"],
].map(([path, names]) => `export { ${names} } from ${JSON.stringify(prefix + path)};`).join("\n");
const compiled = await build({ stdin: { contents: entry, resolveDir: root, sourcefile: "xxm-page-audit.ts" },
  bundle: true, write: false, platform: "node", format: "esm", logLevel: "silent" });
const bundle = `data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`;
const tabs = await Promise.all([import(bundle + "#tab1"), import(bundle + "#tab2")]);
const nativeFetch = globalThis.fetch;
const context = new AsyncLocalStorage();
globalThis.window = { location: { origin: base }, localStorage: { getItem: () => null },
  setTimeout, clearTimeout, dispatchEvent() {} };
const requests = [], rounds = [];
globalThis.fetch = async (input, options) => {
  const url = new URL(String(input), base);
  const record = { ...context.getStore(), path: url.pathname, query: url.search, started: performance.now() };
  requests.push(record);
  try {
    const response = await nativeFetch(url, options);
    record.httpStatus = response.status;
    // Include body transfer in transport timings while returning the same JSON.
    const bytes = await response.arrayBuffer();
    record.seconds = (performance.now() - record.started) / 1000;
    record.bytes = bytes.byteLength;
    if (!response.ok) record.body = new TextDecoder().decode(bytes);
    return new Response(bytes, { status: response.status, headers: response.headers });
  } catch (error) { record.error = String(error); record.seconds = (performance.now() - record.started) / 1000; throw error; }
};
const persist = () => writeFile(resolve(output, "page-mix.json"), JSON.stringify({ rounds, requests }, null, 2) + "\n");
const periods = ["day", "m60", "m90", "m120"];
const endDate = "2026-10-14";
async function runTab(tab, selected, label, tabIndex) {
  return context.run({ label, tab: tabIndex }, async () => {
    const signal = new AbortController().signal;
    // Enqueue predictions first: the real scheduler must prioritize chart reads.
    const predictions = periods.map(period => tab.fetchForecast(period, undefined, signal));
    const chart = selected === "day"
      ? tab.indexDetailRequests.run("chart", () => tab.fetchIndexDetailKline({ tsCode: "000001.SH", period: "day", endDate, limit: 300 }))
      : Promise.all([tab.fetchIndexDetailMinutes({ tsCode: "000001.SH", freq: Number(selected.slice(1)), endDate, limit: 500 }),
        tab.fetchIndexDetailMinuteIndicators({ tsCode: "000001.SH", freq: Number(selected.slice(1)), endDate, limit: 500 })]);
    const nine = ["day", "15", "30", "60", "90", "120"].map(period => tab.loadIndexNineTurnSeries(
      { subjectType: "index", tsCode: "000001.SH", period, endDate, limit: period === "day" ? 300 : 500 }, { signal }));
    const layer = tab.fetchXxm({ tsCode: "000001.SH", period: selected, startDate: "2026-01-01", endDate, limit: 500 }, signal);
    const values = await Promise.all([...predictions, chart, ...nine, layer]);
    for (let i = 0; i < periods.length; i++) {
      const value = values[i], period = periods[i];
      assert.equal(value.period, periods[i]); assert.equal(value.dataStatus, "READY");
      assert.equal(value.computedThrough, periods[i] === "day" ? endDate : `${endDate}T15:00:00+08:00`);
      assert(value.display.targetText && value.display.conditionsText && value.display.asOfText);
      await writeFile(resolve(output, `page-${label}-tab${tabIndex}-${period}.json`), JSON.stringify(value, null, 2) + "\n");
    }
  });
}
for (const selected of periods) {
  for (const tabCount of [1, 2]) {
    for (const mode of ["cold", "warm"]) {
      const label = `${selected}-${tabCount}tabs-${mode}`;
      const reset = await nativeFetch(`${base}/__audit__/reset?fresh=${mode === "cold" ? 1 : 0}`);
      assert(reset.ok);
      const before = requests.length, started = performance.now();
      const settled = await Promise.allSettled(tabs.slice(0, tabCount).map((tab, index) => runTab(tab, selected, label, index + 1)));
      const metrics = await (await nativeFetch(`${base}/__audit__/metrics`)).json();
      const batch = requests.slice(before);
      const row = { label, selected, tabCount, mode, requests: batch.length,
        pageSeconds: (performance.now() - started) / 1000, maxHttpSeconds: Math.max(...batch.map(r => r.seconds)), metrics,
        errors: settled.filter(r => r.status === "rejected").map(r => String(r.reason)) };
      rounds.push(row); await persist(); console.log(JSON.stringify(row));
      assert.equal(row.errors.length, 0, JSON.stringify(row));
      assert(batch.every(r => r.httpStatus === 200 && r.seconds <= 4), JSON.stringify(row));
      assert(metrics.maxComputeSeconds <= .2);
      assert(metrics.cacheBytes <= 64 * 1024 * 1024 && metrics.cacheEntries <= 16);
      // Cold paired tabs share the loaded series, even if their arrival is staggered.
      if (mode === "cold") {
        assert.equal(Object.keys(metrics.completeReads).length, 3);
        assert(Object.values(metrics.completeReads).every(n => n === 2), JSON.stringify(metrics));
      } else assert.equal(Object.keys(metrics.completeReads).length, 0);
    }
  }
}
console.log(JSON.stringify({ status: "PASS", rounds: rounds.length, requests: requests.length }));
