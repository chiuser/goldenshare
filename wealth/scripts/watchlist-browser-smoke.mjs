// Run against tests.wealth_watchlist_browser_fixture, never against a deployed site.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const [base, output, playwrightModule] = process.argv.slice(2);
assert.equal(new URL(base).hostname, "127.0.0.1");
const { chromium } = await import(pathToFileURL(playwrightModule).href);
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 980 } });
const session = await context.request.get(`${base}/test-session`);
assert.equal(session.status(), 200, "This is not the isolated test fixture");
const { token } = await session.json();
await context.addInitScript((accessToken) => {
  localStorage.setItem("wealth.auth.access-token", accessToken);
  window.__watchlistLongTasks = [];
  new PerformanceObserver((entries) => window.__watchlistLongTasks.push(...entries.getEntries().map((entry) => entry.duration))).observe({ type: "longtask", buffered: true });
}, token);
const page = await context.newPage();
const errors = [], requests = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
page.on("request", (request) => { if (request.url().includes("/api/")) requests.push({ url: request.url(), method: request.method() }); });
try {
  const start = performance.now();
  await page.goto(`${base}/wealth/market/watchlist?tradeDate=2026-09-02`);
  await page.waitForFunction(() => document.querySelectorAll(".watchlist-table tbody tr").length === 100);
  const first100ReadyMs = Math.round(performance.now() - start);
  const fields = await page.locator(".watchlist-table tbody tr").evaluateAll((rows) => rows.slice(0, 7).map((row) => ({
    cells: [...row.querySelectorAll("td")].map((cell) => cell.innerText),
    changeClass: row.querySelector(".change-column").className,
    flowClass: row.querySelector(".money-column").className,
  })));
  assert.deepEqual(fields[0].cells, ["000001.SZ", "测试股票1", "12.34", "-1.50", "123.46", "5.62\n0.71", "1.08", "0.92", "-0.22", "银行", "移除"]);
  assert.match(fields[0].changeClass, /\bdown\b/); assert.match(fields[0].flowClass, /\bdown\b/);
  assert.equal(fields[1].cells[3], "0.00"); assert.match(fields[1].changeClass, /\bflat\b/);
  assert.equal(fields[2].cells[3], "+1.73"); assert.equal(fields[2].cells[8], "+0.22");
  assert.match(fields[2].changeClass, /\bup\b/); assert.match(fields[2].flowClass, /\bup\b/);
  assert.equal(fields[4].cells[5], "--\n0.71");
  assert.deepEqual(fields[6].cells.slice(5, 9), ["--\n--", "--", "--", "--"]);
  assert.match(fields[6].flowClass, /\bwatchlist-missing\b/);
  assert.equal(await page.getByText("部分数据缺失，缺失字段以 -- 展示。", { exact: true }).count(), 1);
  const table = page.locator(".watchlist-table-scroll");
  const layout = await page.evaluate(() => {
    const headers = [...document.querySelectorAll(".watchlist-table th")];
    const cells = [...document.querySelectorAll(".watchlist-table tbody tr:first-child td")];
    const textLeft = (element) => {
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      let text;
      while ((text = walker.nextNode())) {
        if (!text.textContent.trim()) continue;
        const range = document.createRange(); range.selectNodeContents(text);
        return range.getBoundingClientRect().left;
      }
    };
    return headers.map((header, index) => ({ label: header.textContent, headerLeft: textLeft(header), contentLeft: textLeft(cells[index]),
      headerAlign: getComputedStyle(header).textAlign, contentAlign: getComputedStyle(cells[index]).textAlign,
      position: getComputedStyle(cells[index]).position, rowHeight: cells[index].getBoundingClientRect().height, left: cells[index].getBoundingClientRect().left }));
  });
  for (const column of layout) {
    assert.equal(column.headerAlign, "left"); assert.equal(column.contentAlign, "left");
    assert.ok(Math.abs(column.headerLeft - column.contentLeft) < 1, `text-left mismatch: ${JSON.stringify(column)}`);
    assert.equal(column.rowHeight, 60);
  }
  assert.deepEqual(layout.filter((column) => column.position === "sticky").map((column) => column.label), ["股票代码", "股票名称", "操作"]);
  const geometry = await table.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth }));
  assert.ok(geometry.scroll > geometry.client);
  await page.evaluate(() => { window.__watchlistLongTasks = []; });
  await table.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  const afterScroll = await page.locator(".watchlist-table tbody tr:first-child td").evaluateAll((cells) => cells.map((cell) => ({ left: cell.getBoundingClientRect().left, right: cell.getBoundingClientRect().right })));
  for (const index of [0, 1, 10]) assert.ok(Math.abs(afterScroll[index].left - layout[index].left) < 1);
  assert.ok(afterScroll[9].left < layout[9].left); assert.ok(Math.abs(afterScroll[9].right - afterScroll[10].left) < 1);
  const centeredTag = await page.locator(".watchlist-sector-tag").first().evaluate((tag) => {
    const cell = tag.closest("td").getBoundingClientRect(), badge = tag.getBoundingClientRect();
    return Math.abs((cell.top + cell.bottom) / 2 - (badge.top + badge.bottom) / 2);
  });
  assert.ok(centeredTag <= 1);
  await table.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await page.waitForFunction(() => document.querySelectorAll(".watchlist-table tbody tr").length === 200);
  await table.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await page.locator(".watchlist-table tbody tr").last().waitFor({ state: "visible" });
  const scrollingLongTasks = await page.evaluate(() => window.__watchlistLongTasks);
  assert.equal(requests.filter((request) => new URL(request.url).pathname === "/api/v1/wealth/market/watchlist").length, 2);
  await table.evaluate((element) => { element.scrollTop = 0; element.scrollLeft = 0; });
  await page.screenshot({ path: `${output}/watchlist-ready.png` });
  await page.getByRole("button", { name: "+ 添加自选", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "添加自选" });
  assert.equal(await dialog.locator(".watchlist-search-body").innerText(), "");
  const blankHeight = (await dialog.boundingBox()).height;
  await page.screenshot({ path: `${output}/watchlist-add-empty.png` });
  await dialog.getByPlaceholder("输入名称首字母或代码").fill("CSGP20");
  await dialog.getByRole("button", { name: "添加 测试股票201 000201.SZ", exact: true }).waitFor();
  assert.ok(await dialog.getByText("已添加", { exact: true }).count() >= 1);
  assert.equal((await dialog.boundingBox()).height, blankHeight);
  await page.screenshot({ path: `${output}/watchlist-add-results.png` });
  await dialog.getByRole("button", { name: "添加 测试股票201 000201.SZ", exact: true }).click();
  await dialog.getByText("已添加到列表末尾").waitFor(); assert.equal(await dialog.isVisible(), true);
  await dialog.getByRole("button", { name: "完成", exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll(".watchlist-table tbody tr").length === 201);
  assert.ok((await page.locator(".watchlist-table tbody tr").last().innerText()).includes("000201.SZ"));
  await page.getByRole("button", { name: "移除 测试股票201 000201.SZ", exact: true }).click();
  const removal = page.getByRole("dialog", { name: "确认移除「测试股票201」？" });
  const box = await removal.boundingBox();
  assert.ok(Math.abs(box.x + box.width / 2 - 800) < 1); assert.ok(Math.abs(box.y + box.height / 2 - 490) < 1);
  await page.screenshot({ path: `${output}/watchlist-remove-centered.png` });
  await page.keyboard.press("Escape"); assert.equal(await removal.isVisible(), false);
  await page.getByRole("button", { name: "移除 测试股票201 000201.SZ", exact: true }).click();
  await removal.getByRole("button", { name: "确认移除" }).click();
  await page.waitForFunction(() => document.querySelectorAll(".watchlist-table tbody tr").length === 200);
  await table.evaluate((element) => { element.scrollTop = 0; });
  await page.getByRole("button", { name: "000001.SZ", exact: true }).click();
  await page.getByRole("button", { name: "已自选", exact: true }).waitFor();
  const kline = requests.find((request) => request.url.includes("/stock-detail/kline"));
  assert.equal(new URL(kline.url).searchParams.get("period"), "day");
  assert.equal(new URL(kline.url).searchParams.get("adjustment"), "forward");
  assert.equal(errors.length, 0, errors.join("\n"));
  // This fixture intentionally mounts only the routes in this feature's scope.
  // The other homepage modules return 404, not fabricated successful payloads.
  const home = await context.newPage(), homepageErrors = [], homepageResponses = [];
  home.on("pageerror", (error) => homepageErrors.push(error.message));
  home.on("response", (response) => {
    if (response.url().includes("/api/")) homepageResponses.push({ url: response.url(), status: response.status() });
  });
  await home.goto(`${base}/wealth/market/overview?tradeDate=2026-09-02`);
  const shortcut = home.getByRole("button", { name: /我的自选/ });
  await shortcut.getByText("200", { exact: true }).waitFor();
  const summary = homepageResponses.find((response) => response.url.endsWith("/watchlist/summary"));
  assert.equal(summary?.status, 200);
  await shortcut.click();
  await home.waitForURL(/\/wealth\/market\/watchlist$/);
  await home.waitForFunction(() => document.querySelectorAll(".watchlist-table tbody tr").length === 100);
  assert.deepEqual(homepageErrors, []);
  await home.close();
  const expired = await browser.newContext({ viewport: { width: 1600, height: 980 } });
  await expired.addInitScript(() => { localStorage.setItem("wealth.auth.access-token", "invalid-test-token"); });
  const unauthenticated = await expired.newPage();
  await unauthenticated.goto(`${base}/wealth/market/watchlist`);
  await unauthenticated.waitForURL(/\/wealth\/login\?redirect=/);
  assert.ok(unauthenticated.url().includes("redirect=%2Fwealth%2Fmarket%2Fwatchlist"));
  await expired.close();
  await writeFile(`${output}/watchlist-browser-evidence.json`, JSON.stringify({ first100ReadyMs, fields, layout, geometry, centeredTagOffset: centeredTag, homepageResponses, homepageErrors,
    scrollingLongTasks, addDialogHeight: blankHeight, removeDialog: box, errors, requests }, null, 2));
  console.log(JSON.stringify({ first100ReadyMs, rowCount: 200, columnCount: layout.length, scrollingLongTasks, addDialogHeight: blankHeight, removeDialog: box, errors }));
} catch (error) {
  await page.screenshot({ path: `${output}/watchlist-failure.png` }); throw error;
} finally { await browser.close(); }
