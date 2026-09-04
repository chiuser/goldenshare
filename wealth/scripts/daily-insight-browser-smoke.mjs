// Only run against the disposable fixture created by daily-insight-browser-fixture.py.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const [base, output, playwrightModule] = process.argv.slice(2);
assert.equal(new URL(base).hostname, "127.0.0.1");
const { chromium } = await import(pathToFileURL(playwrightModule).href);
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
const identity = await context.request.get(`${base}/test-fixture`);
assert.equal((await identity.json()).kind, "daily-insight-isolated-sqlite");
await context.addInitScript(() => localStorage.setItem("wealth.auth.access-token", "isolated-fixture"));
const page = await context.newPage();
const errors = [], requests = [], checks = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
page.on("request", (request) => { if (request.url().includes("/api/")) requests.push(new URL(request.url()).pathname); });
const route = `${base}/wealth/exploration/sector-analysis/daily-insight`;
const ready = () => page.getByRole("table", { name: "头部上涨完整列表" }).waitFor();
const pauseForLayout = () => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
try {
  const start = performance.now();
  await page.goto(route); await ready();
  checks.push({ firstReadyMs: performance.now() - start });
  assert.equal(await page.locator(".daily-insight-row").count(), 320);
  assert.equal(requests.filter((path) => path.includes("daily-insight/meta")).length, 1);
  assert.equal(requests.filter((path) => path.includes("daily-insight/snapshot")).length, 1);
  assert.ok(requests.filter((path) => path.includes("sector-analysis")).every((path) => path.includes("daily-insight")));
  for (const width of [1600, 1512, 1460, 1366]) {
    await page.setViewportSize({ width, height: 1100 }); await pauseForLayout();
    const geometry = await page.locator(".daily-insight-panel").evaluateAll((panels) => panels.map((panel) => {
      const box = panel.getBoundingClientRect();
      const row = panel.querySelector(".daily-insight-row");
      const head = panel.querySelector(".daily-insight-header");
      const cells = [...row.children], headers = [...head.children];
      const center = (element) => { const r = element.getBoundingClientRect(); return r.left + r.width / 2; };
      return {
        width: box.width, height: box.height, rowHeight: row.getBoundingClientRect().height,
        overflow: panel.scrollWidth > panel.clientWidth,
        headerHeight: head.getBoundingClientRect().height,
        viewportHeight: panel.querySelector(".daily-insight-scroll").getBoundingClientRect().height,
        deltas: cells.map((cell, i) => center(cell) - center(headers[i])),
        numericAlignment: cells.slice(1, 5).map((cell) => center(cell.firstElementChild) - center(cell)),
        tag: { width: row.querySelector(".daily-insight-fact-tag").getBoundingClientRect().width, height: row.querySelector(".daily-insight-fact-tag").getBoundingClientRect().height },
        reasonHeight: row.querySelector(".daily-insight-reason").getBoundingClientRect().height,
      };
    }));
    for (const g of geometry) {
      assert.equal(g.height, 348); assert.equal(g.rowHeight, 60); assert.equal(g.headerHeight, 28); assert.equal(g.viewportHeight, 262);
      assert.equal(g.overflow, false); assert.ok(g.deltas.every((d) => Math.abs(d) <= 1)); assert.ok(g.numericAlignment.every((d) => Math.abs(d) <= 1));
      assert.equal(g.tag.height, 24); assert.ok(g.tag.width <= 80); assert.ok(g.reasonHeight <= 32);
      if (width === 1600) assert.equal(g.width, 776);
    }
    checks.push({ width, geometry });
    await page.screenshot({ path: `${output}/ready-${width}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1600, height: 1100 });
  const scrolls = page.locator(".daily-insight-scroll");
  await scrolls.first().evaluate((node) => { node.scrollTop = node.scrollHeight; });
  assert.equal(await scrolls.nth(1).evaluate((node) => node.scrollTop), 0);
  assert.equal(await scrolls.first().locator(".daily-insight-row").count(), 80);
  assert.equal(await scrolls.first().locator(".daily-insight-row").last().evaluate((row) => getComputedStyle(row).boxShadow), "none");
  await scrolls.first().evaluate((node) => { node.scrollTop = 0; });
  await page.evaluate(() => window.scrollTo(0, 350));
  const trigger = scrolls.first().locator(".daily-insight-reason").first();
  await trigger.click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  const center = await dialog.evaluate((node) => { const r = node.getBoundingClientRect(); return { x: r.x + r.width / 2 - innerWidth / 2, y: r.y + r.height / 2 - innerHeight / 2, width: r.width, height: r.height, position: getComputedStyle(node).position }; });
  assert.ok(Math.abs(center.x) <= 1 && Math.abs(center.y) <= 1); assert.equal(center.width, 380); assert.equal(center.position, "fixed");
  const fullText = await trigger.getAttribute("title");
  assert.equal(await dialog.locator(".daily-insight-explanation-text").textContent(), fullText);
  checks.push({ centeredAfterScroll: center });
  await page.screenshot({ path: `${output}/explanation-centered.png` });
  await page.keyboard.press("Escape"); assert.equal(await dialog.count(), 0);
  assert.ok(await trigger.evaluate((node) => document.activeElement === node));
  await trigger.click(); await page.mouse.click(10, 200); assert.equal(await dialog.count(), 0);
  await trigger.click(); await page.getByRole("button", { name: "关闭", exact: true }).click(); assert.equal(await dialog.count(), 0);
  await trigger.click(); await page.evaluate(() => window.scrollBy(0, -5)); await dialog.waitFor({ state: "detached" });

  const metaCalls = requests.filter((path) => path.endsWith("daily-insight/meta")).length;
  for (const label of ["二级行业", "三级行业"]) {
    await page.getByRole("button", { name: label, exact: true }).click(); await ready();
    await page.waitForFunction((name) => document.querySelector(".daily-insight-overview-meta")?.textContent.includes(name), label);
    await page.screenshot({ path: `${output}/ready-${label}.png`, fullPage: true });
  }
  assert.equal(requests.filter((path) => path.endsWith("daily-insight/meta")).length, metaCalls);
  await page.getByLabel("分析日期", { exact: true }).selectOption("2025-08-22");
  await page.getByText("所选交易日的每日洞察尚未发布。").waitFor();
  assert.equal(await page.locator(".daily-insight-row").count(), 0);
  await page.screenshot({ path: `${output}/historical-missing.png`, fullPage: true });
  // Bounded layout variants replay the same real API response with fewer test rows.
  // These are synthetic visual cases, never evidence about production data.
  for (const count of [0, 1, 3, 4, 5]) {
    await page.route("**/daily-insight/snapshot?*", async (intercept) => {
      const response = await intercept.fetch();
      const data = await response.json();
      for (const key of ["headGainers", "headLosers", "strengthening", "weakening"]) data[key] = data[key].slice(0, count);
      Object.assign(data.summary, { upCount: count, downCount: count, flatCount: data.summary.calculableCount - 2 * count });
      await intercept.fulfill({ response, json: data });
    });
    await page.goto(route); await ready(); await pauseForLayout();
    const layout = await page.locator(".daily-insight-panel").first().evaluate((panel) => {
      const viewport = panel.querySelector(".daily-insight-scroll");
      const rows = [...viewport.querySelectorAll(".daily-insight-row")];
      const headers = [...panel.querySelector(".daily-insight-header").children];
      const left = (element) => element.getBoundingClientRect().left;
      return { count: rows.length, height: panel.getBoundingClientRect().height, scrollable: viewport.scrollHeight > viewport.clientHeight,
        unusedHeight: viewport.clientHeight - rows.length * 60,
        leftDeltas: rows.length ? [0, 6].map((i) => left(rows[0].children[i]) - left(headers[i])) : [],
        shadows: rows.map((row) => getComputedStyle(row).boxShadow) };
    });
    assert.equal(layout.count, count); assert.equal(layout.height, 348); assert.equal(layout.scrollable, count >= 5);
    assert.ok(layout.leftDeltas.every((delta) => Math.abs(delta) <= 1));
    if (count) { assert.equal(layout.shadows.at(-1), "none"); assert.ok(layout.shadows.slice(0, -1).every((shadow) => shadow !== "none")); }
    if (count === 3) assert.equal(layout.unusedHeight, 82);
    await page.screenshot({ path: `${output}/list-${count}-rows.png`, fullPage: true });
    checks.push({ layoutVariant: layout });
    await page.unroute("**/daily-insight/snapshot?*");
  }
  // Synthetic transport states exercise the same page, without production reads.
  await page.route("**/daily-insight/meta?*", async (intercept) => {
    const response = await intercept.fetch(); const data = await response.json();
    data.status = "DELAYED"; data.coverageEndDate = "2025-08-26";
    Object.assign(data.dateContext, { requestedTradeDate: "2025-08-26", isDelayed: true, delayReason: "目标日批次尚未发布" });
    data.tradeDates.push({ tradeDate: "2025-08-26", availability: "MISSING", batchKey: null, hierarchyVersion: null, publishedAt: null });
    await intercept.fulfill({ response, json: data });
  });
  await page.goto(route); await ready(); await page.getByText("当前展示 2025-08-25 盘后数据").waitFor();
  assert.equal(await page.locator(".daily-insight-row").count(), 320);
  await page.screenshot({ path: `${output}/delayed.png`, fullPage: true });
  await page.unroute("**/daily-insight/meta?*");
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  await page.route("**/daily-insight/meta?*", async (intercept) => { await held; await intercept.continue(); });
  try {
    await page.goto(route); await page.locator(".daily-insight-state.loading").waitFor();
    await page.screenshot({ path: `${output}/loading.png`, fullPage: true });
  } finally { release(); }
  await ready(); await page.unroute("**/daily-insight/meta?*");
  await page.route("**/daily-insight/meta?*", (intercept) => intercept.fulfill({ status: 200, json: { privateSql: "must not be shown" } }));
  await page.goto(route); await page.locator(".daily-insight-state.error").waitFor();
  assert.equal(await page.locator(".daily-insight-row").count(), 0);
  assert.ok(!(await page.locator("body").textContent()).includes("must not be shown"));
  await page.screenshot({ path: `${output}/error.png`, fullPage: true });
  await page.unroute("**/daily-insight/meta?*");
  assert.equal(errors.length, 0, JSON.stringify(errors));
  checks.push({ errors, requests, fullLists: 320, independentScroll: true, missingDoesNotFallback: true, closePaths: ["button", "outside", "Escape", "background-scroll"] });
  await writeFile(`${output}/checks.json`, JSON.stringify(checks, null, 2));
  console.log(JSON.stringify({ passed: true, output, checks: checks.length }));
} finally { await browser.close(); }
