// Non-browser integration driver. Vite only loads the real TS modules in memory.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createServer } from "../wealth/node_modules/vite/dist/node/index.js";

const config = JSON.parse(readFileSync(0, "utf8"));
const origin = new URL(config.origin);
assert.equal(origin.hostname, "127.0.0.1");
assert.equal(origin.protocol, "http:");
assert.ok(origin.port);
const storage = new Map();
globalThis.window = Object.assign(new EventTarget(), {
  location: { origin: origin.origin }, setTimeout, clearTimeout,
  localStorage: {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  },
});
const nativeFetch = globalThis.fetch;
const requests = [];
globalThis.fetch = async (input, init) => {
  const target = new URL(input, origin);
  assert.equal(target.origin, origin.origin, "Test must never contact another server");
  const response = await nativeFetch(target, init);
  requests.push({ method: init?.method ?? "GET", path: target.pathname, status: response.status });
  return response;
};
const loader = await createServer({
  root: fileURLToPath(new URL("../wealth", import.meta.url)), configFile: false,
  logLevel: "error", optimizeDeps: { noDiscovery: true, include: [] },
  server: { middlewareMode: true, watch: null, hmr: false }, appType: "custom",
});

try {
  const api = await loader.ssrLoadModule("/src/features/watchlist/api/watchlistApi.ts");
  const auth = await loader.ssrLoadModule("/src/features/auth/model/authStorage.ts");
  const { buildWatchlistRow } = await loader.ssrLoadModule("/src/features/watchlist/model/watchlistViewModelAdapter.ts");
  const login = id => auth.saveAuthSession({ token: config.tokens[id], username: `watchlist-test-${id}` });
  const reject = (call, code, outcome = "FAILED") => assert.rejects(call, e => e.code === code && e.outcome === outcome);
  const page = (groupId, rest = {}) => api.fetchWatchlistPage({ groupId, tradeDate: "2026-09-02", ...rest });
  const create = async (name, color) => (await api.createWatchlistGroup({ name, color })).group;
  const defaultGroup = async () => (await api.fetchWatchlistGroups()).groups.find(g => g.isDefault);

  if (config.mode !== "contracts") {
    login({ unknown: 10, failed: 11, "refresh-failed": 12 }[config.mode]);
    const before = await api.fetchWatchlistGroups();
    const name = config.mode === "unknown" ? "未知结果" : config.mode === "failed" ? "明确失败" : "刷新失败";
    const write = () => create(name, before.rules.palette[0]);
    if (config.mode === "unknown") await reject(write, "WL_WRITE_OUTCOME_UNKNOWN", "UNKNOWN");
    else if (config.mode === "failed") await reject(write, "WL_WRITE_FAILED");
    else {
      assert.equal((await write()).name, name);
      await reject(() => api.fetchWatchlistGroups(), "WL_QUERY_FAILED");
    }
    const after = await api.fetchWatchlistGroups();
    const persisted = after.groups.some(g => g.name === name);
    assert.equal(persisted, config.mode !== "failed");
    const writes = requests.filter(r => r.method !== "GET").length;
    assert.equal(writes, 1);
    console.log(JSON.stringify({ mode: config.mode, writes, persisted, requests: requests.length }));
  } else {
    auth.clearAuthSession();
    await assert.rejects(() => api.fetchWatchlistGroups());
    assert.equal(requests.at(-1).status, 401);
    login(1);
    const initial = await api.fetchWatchlistGroups();
    const d = initial.groups[0];
    assert.equal(d.name, "我的自选");
    assert.equal(d.isDefault, true);
    assert.equal(d.color, null);
    assert.equal(initial.rules.maxGroups, 10);
    assert.equal(initial.rules.maxBatchMemberships, 200);
    const [color, otherColor] = initial.rules.palette;
    assert.equal(initial.rules.palette.length, 8);
    assert.equal((await page(d.id)).dataStatus.status, "EMPTY");
    const a = await create("  联调甲  ", color);
    const b = await create("联调乙", color);
    assert.equal(a.name, "联调甲");
    await reject(() => create("联调甲", color), "WL_GROUP_NAME_CONFLICT");
    await reject(() => api.deleteWatchlistGroup(d.id), "WL_DEFAULT_GROUP_IMMUTABLE");
    await reject(() => api.changeWatchlistGroupColor(d.id, color), "WL_DEFAULT_GROUP_IMMUTABLE");
    await reject(() => create("我的自选", color), "WL_REQUEST_INVALID");
    await reject(() => create("非法颜色", "#000000"), "WL_REQUEST_INVALID");
    assert.equal((await api.changeWatchlistGroupColor(b.id, otherColor)).group.color, otherColor);
    await api.changeWatchlistGroupColor(b.id, color);
    assert.equal((await api.addWatchlistGroupItem(a.id, "000001.sz")).created, true);
    assert.equal((await api.addWatchlistGroupItem(a.id, "000001.SZ")).created, false);
    assert.equal((await api.fetchWatchlistSummary()).totalCount, 0);
    assert.equal((await api.searchWatchlistCandidates({ groupId: a.id, keyword: "000001" })).items[0].status, "ADDED");
    assert.equal((await api.searchWatchlistCandidates({ groupId: b.id, keyword: "000001" })).items[0].status, "AVAILABLE");
    const first = (await page(a.id)).items[0];
    const ids = [first.membershipId];
    assert.equal(first.quote.price, 12.34);
    assert.equal(first.quote.vol, 1234567);
    assert.equal(buildWatchlistRow(first).vol, "123.46");
    assert.equal(buildWatchlistRow(first).netAmount, "-2189.40");
    assert.equal((await api.batchWatchlistItems(a.id, "ADD_TO_GROUPS", ids, [b.id, d.id])).createdCount, 2);
    assert.equal((await api.fetchWatchlistSummary()).totalCount, 1);
    assert.deepEqual((await page(a.id)).items[0].groupMarks.map(m => m.groupId), [a.id, b.id]);
    assert.deepEqual((await page(a.id)).items[0].groupMarks.map(m => m.color), [color, color]);
    await api.batchWatchlistItems(a.id, "PIN", ids);
    assert.equal((await page(a.id)).items[0].isPinned, true);
    await api.batchWatchlistItems(a.id, "UNPIN", ids);
    assert.equal((await page(a.id)).items[0].isPinned, false);
    const targetId = (await page(b.id)).items[0].membershipId;
    const moved = await api.batchWatchlistItems(a.id, "MOVE", ids, [b.id]);
    assert.equal(moved.createdCount, 0);
    assert.equal(moved.removedCount, 1);
    assert.equal((await page(b.id)).items[0].membershipId, targetId);
    await reject(() => api.batchWatchlistItems(a.id, "REMOVE", ids), "WL_SELECTION_STALE");
    const replaced = await api.replaceStockWatchlistGroups("000001.SZ", [b.id]);
    assert.equal(replaced.removedCount, 1);
    assert.equal((await api.fetchWatchlistSummary()).totalCount, 0);
    const selected = await api.fetchStockWatchlistGroups("000001.SZ");
    assert.deepEqual(selected.groups.filter(g => g.selected).map(g => g.groupId), [b.id]);
    await reject(() => api.replaceStockWatchlistGroups("000001.SZ", []), "WL_MEMBERSHIP_REQUIRED");
    await api.batchWatchlistItems(b.id, "REMOVE", [targetId]);
    assert.equal((await api.fetchStockWatchlistGroups("000001.SZ")).isAdded, false);

    login(2);
    const foreign = await defaultGroup();
    await reject(() => page(a.id), "WL_GROUP_NOT_FOUND");
    await reject(() => api.addWatchlistGroupItem(a.id, "000001.SZ"), "WL_GROUP_NOT_FOUND");
    const ownItem = (await page(foreign.id)).items[0].membershipId;
    await reject(() => api.batchWatchlistItems(foreign.id, "MOVE", [ownItem], [a.id]), "WL_TARGET_GROUP_INVALID");
    assert.equal((await page(foreign.id)).totalCount, 20);
    login(1);
    await reject(() => api.replaceStockWatchlistGroups("000001.SZ", [foreign.id]), "WL_TARGET_GROUP_INVALID");
    assert.equal((await api.deleteWatchlistGroup(a.id)).nextGroupId, b.id);
    assert.equal((await api.deleteWatchlistGroup(b.id)).nextGroupId, d.id);

    login(4);
    const full = await defaultGroup();
    const base = await page(full.id, { limit: 200 });
    assert.equal(base.items.length, 200);
    assert.equal(base.dataStatus.status, "PARTIAL");
    const missing = base.items.find(i => i.stock.tsCode === "000007.SZ");
    assert.equal(missing.valuation.peTtm, null);
    assert.equal(missing.moneyFlow.netAmount, null);
    assert.equal(buildWatchlistRow(missing).peTtm, "--");
    assert.equal(buildWatchlistRow(missing).netAmount, "--");
    const zero = base.items.find(i => i.stock.tsCode === "000002.SZ");
    assert.equal(zero.quote.changePct, 0);
    assert.equal(zero.moneyFlow.netAmount, 0);
    assert.equal(buildWatchlistRow(zero).netAmount, "0.00");
    const pinned = base.items.slice(0, 3).map(i => i.membershipId);
    await api.batchWatchlistItems(full.id, "PIN", pinned);
    assert.deepEqual((await page(full.id)).items.slice(0, 3).map(i => i.membershipId), [...pinned].reverse());
    const fields = {
      price: i => i.quote.price, changePct: i => i.quote.changePct, vol: i => i.quote.vol,
      peTtm: i => i.valuation.peTtm, pb: i => i.valuation.pb,
      volumeRatio: i => i.activity.volumeRatio, turnoverRate: i => i.activity.turnoverRate,
      netAmount: i => i.moneyFlow.netAmount,
    };
    let sortTraversals = 0;
    for (const [sortBy, value] of Object.entries(fields)) for (const direction of ["desc", "asc"]) {
      const rows = [];
      let cursor;
      do {
        const batch = await page(full.id, { limit: 37, sortBy, direction, cursor });
        rows.push(...batch.items);
        cursor = batch.nextCursor ?? undefined;
      } while (cursor);
      assert.equal(rows.length, 200);
      assert.equal(new Set(rows.map(i => i.membershipId)).size, 200);
      const expected = [...base.items].map(i => ({ ...i, isPinned: pinned.includes(i.membershipId) })).sort((a, b) => {
        if (a.isPinned !== b.isPinned) return a.isPinned ? -1 : 1;
        const x = value(a), y = value(b);
        if (x !== y) {
          if (x === null) return 1;
          if (y === null) return -1;
          return (x - y) * (direction === "asc" ? 1 : -1);
        }
        return (a.membershipId - b.membershipId) * (a.isPinned ? -1 : 1);
      });
      assert.deepEqual(rows.map(i => i.membershipId), expected.map(i => i.membershipId));
      sortTraversals++;
    }
    const cursor = (await page(full.id, { limit: 1 })).nextCursor;
    await reject(() => page(full.id, { cursor, sortBy: "price", direction: "desc" }), "WL_CURSOR_INVALID");
    await reject(() => page(full.id, { cursor: "broken" }), "WL_CURSOR_INVALID");
    await api.batchWatchlistItems(full.id, "UNPIN", pinned);
    assert.deepEqual((await page(full.id, { limit: 200 })).items.map(i => i.membershipId), base.items.map(i => i.membershipId));

    const measurements = {};
    const measure = async (name, limit, operation) => {
      const start = performance.now();
      const result = await operation();
      const sample = performance.now() - start;
      (measurements[name] ??= { budgetMs: limit, samples: [] }).samples.push(sample);
      return result;
    };
    for (let n = 0; n < 30; n++) {
      await measure("groups", 200, () => api.fetchWatchlistGroups());
      await measure("summary", 200, () => api.fetchWatchlistSummary());
      await measure("stockGroups", 200, () => api.fetchStockWatchlistGroups("000001.SZ"));
      await measure("search", 200, () => api.searchWatchlistCandidates({ groupId: full.id, keyword: "CSGP1" }));
      for (const limit of [100, 200]) {
        const result = await measure(`items${limit}`, limit === 100 ? 300 : 500, () => page(full.id, { limit }));
        assert.ok(Buffer.byteLength(JSON.stringify(result)) <= (limit === 100 ? 256 : 512) * 1024);
      }
      const group = await measure("create", 300, () => create("性能组", color));
      await measure("color", 300, () => api.changeWatchlistGroupColor(group.id, otherColor));
      assert.equal((await measure("add", 300, () => api.addWatchlistGroupItem(group.id, "000001.SZ"))).created, true);
      const deleted = await api.deleteWatchlistGroup(group.id);
      assert.equal(deleted.deletedMemberCount, 1);
      assert.equal(deleted.nextGroupId, full.id);
    }
    for (let owner = 20; owner < 50; owner++) {
      login(owner);
      const source = await defaultGroup();
      const memberIds = (await page(source.id, { limit: 200 })).items.map(i => i.membershipId);
      const targets = [];
      for (let i = 0; i < 9; i++) targets.push((await create(`目标${i}`, color)).id);
      await reject(() => create("第十组", color), "WL_GROUP_LIMIT_REACHED");
      const result = await measure("batch200x9", 800, () => api.batchWatchlistItems(source.id, "ADD_TO_GROUPS", memberIds, targets));
      assert.equal(result.createdCount, 1800);
      assert.equal(result.requestedCount, 200);
      assert.equal((await api.batchWatchlistItems(source.id, "ADD_TO_GROUPS", memberIds, targets)).createdCount, 0);
      if (owner === 20) {
        await reject(() => api.batchWatchlistItems(source.id, "PIN", [...memberIds, 9007199254740991]), "WL_REQUEST_INVALID");
        await reject(() => api.batchWatchlistItems(source.id, "PIN", []), "WL_REQUEST_INVALID");
        assert.equal((await page(targets[0], { limit: 200 })).totalCount, 200);
      }
    }
    const performanceReport = Object.fromEntries(Object.entries(measurements).map(([name, record]) => {
      assert.equal(record.samples.length, 30);
      record.samples.sort((a, b) => a - b);
      const p95 = record.samples[Math.ceil(record.samples.length * 0.95) - 1];
      assert.ok(p95 <= record.budgetMs, `${name} P95 ${p95} > ${record.budgetMs} ms`);
      return [name, { p95Ms: Number(p95.toFixed(2)), budgetMs: record.budgetMs, samples: 30 }];
    }));
    const contracts = new Set(requests.filter(r => r.status === 200).map(r => `${r.method} ${r.path
      .replace(/\/groups\/\d+/g, "/groups/{groupId}")
      .replace(/\/items\/[^/]+$/, "/items/{tsCode}")
      .replace(/\/stocks\/[^/]+/, "/stocks/{tsCode}")}`));
    assert.equal(contracts.size, 15);
    console.log(JSON.stringify({ contracts: contracts.size, sortTraversals, performanceSamples: 30,
      requests: requests.length, performance: performanceReport }));
  }
} finally {
  await loader.close();
  globalThis.fetch = nativeFetch;
  delete globalThis.window;
}
