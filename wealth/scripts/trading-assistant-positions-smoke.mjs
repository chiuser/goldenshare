// New local isolated fixture only. Never accepts a production host.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
const [base, output, playwrightModule] = process.argv.slice(2);
assert.equal(new URL(base).hostname, "127.0.0.1");
const { chromium } = await import(pathToFileURL(playwrightModule).href);
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 980 } });
const session = await (await context.request.get(base + "/test-session?user_id=2")).json();
assert.equal(session.fixture, "trading-assistant-isolated");
const root = base + "/api/v1/wealth/market/trading-assistant";
const headers = { Authorization: "Bearer " + session.token };
const accounts = [];
async function waitPublished(account) {
  let last;
  const until = Date.now() + 30000;
  while (Date.now() < until) {
    const response = await context.request.get(`${root}/accounts/${account}/calculation-status`, { headers });
    assert.equal(response.status(), 200);
    last = await response.json();
    if (last.stage === "PUBLISHED") return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("Publication timeout " + JSON.stringify(last));
}
try {
  for (const [index, count] of [11, 1].entries()) {
    const response = await context.request.post(root + "/accounts", { headers, data: {
      requestId: randomUUID(), attemptId: randomUUID(), name: `图形验收${index}`, brokerName: "验收券商", initialCash: "1000.00",
      commissionRateWan: "3.00", minimumCommission: index ? "10.00" : "5.00", stampTaxRatePct: "0.05",
      initialPositions: Array.from({ length: count }, (_, i) => ({ clientRowId: String(i), tsCode: `${String(101 + i).padStart(6, "0")}.SZ`, openedOn: "2026-09-11", quantity: 100, availableQuantity: 100, costPrice: "10.00" })),
    } });
    assert.equal(response.status(), 201, await response.text());
    const id = (await response.json()).result.account.accountId;
    accounts.push(id); await waitPublished(id);
  }
  await context.addInitScript(token => localStorage.setItem("wealth.auth.access-token", token), session.token);
  const page = await context.newPage(), errors = [], requests = [], failed = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("request", request => { if (request.url().includes("/positions")) requests.push(request.url()); });
  page.on("response", response => { if (response.status() >= 400 && response.url().includes("trading-assistant")) failed.push({ url: response.url(), status: response.status() }); });
  await page.goto(base + "/wealth/market/trading-assistant");
  await page.getByLabel("交易账户", { exact: true }).selectOption("ALL");
  await page.getByRole("heading", { name: "当前持仓" }).waitFor();
  assert.equal(await page.locator(".ta-positions-table tbody tr").count(), 11);
  const summary = page.getByLabel("持仓摘要");
  assert.match(await summary.innerText(), /18,700.00/);
  assert.match(await summary.innerText(), /6,625.65/);
  const bounds = await summary.locator(".ta-position-metric").evaluateAll(nodes => nodes.map(node => ({ x: node.getBoundingClientRect().x, width: node.getBoundingClientRect().width, y: node.getBoundingClientRect().y })));
  assert.equal(new Set(bounds.map(bound => bound.width)).size, 1);
  assert.equal(new Set(bounds.map(bound => bound.y)).size, 1);
  await page.screenshot({ path: output + "-list.png" });
  const baseline = requests.length;
  for (const view of ["条形图", "饼图", "盈亏地图", "列表"]) {
    await page.getByRole("group", { name: "持仓视图" }).getByRole("button", { name: view, exact: true }).click();
    if (view !== "列表") assert.match(await summary.innerText(), /33.69%/);
    if (view === "条形图") assert.equal(await page.locator(".ta-position-bar-row").count(), 11);
    if (view === "盈亏地图") assert.equal(await page.locator(".ta-position-map g").count(), 11);
    if (view === "饼图") {
      assert.equal(await page.locator(".ta-position-pie svg path").count(), 8);
      await page.getByRole("button", { name: "总资产（含现金）", exact: true }).click();
      assert.equal(await page.locator(".ta-position-pie svg path").count(), 9);
      await page.locator(".ta-position-pie-legend > div > button").filter({ hasText: "其他" }).hover();
      assert.equal(await page.getByRole("region", { name: "其他持仓完整明细" }).getByRole("button").count(), 4);
      assert.match(await summary.innerText(), /33.69%/);
    }
    await page.screenshot({ path: output + `-${view}.png` });
  }
  assert.equal(requests.length, baseline, "View changes must reuse the same response");
  const viewChangeRequests = requests.length - baseline;
  await page.getByRole("button", { name: "持仓样本01", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("heading", { name: "验收券商 · 图形验收0", exact: true }).waitFor();
  assert.equal(await dialog.locator(".ta-position-round").count(), 2);
  assert.equal(await dialog.getByRole("button", { name: "记录卖出", exact: true }).isDisabled(), true);
  await dialog.getByLabel("卖出账户").selectOption(accounts[1]);
  await page.screenshot({ path: output + "-detail.png" });
  await dialog.getByRole("button", { name: "记录卖出", exact: true }).click();
  await page.getByRole("heading", { name: "记录卖出", exact: true }).waitFor();
  assert.equal(await page.getByLabel("成交价格", { exact: false }).inputValue(), "");
  assert.equal(await page.getByLabel("成交数量", { exact: false }).inputValue(), "");
  assert.match(await page.getByRole("dialog").innerText(), /持仓样本01/);
  assert.equal(errors.length, 0, JSON.stringify(errors));
  assert.equal(failed.length, 0, JSON.stringify(failed));
  await page.getByRole("dialog").getByRole("button", { name: "取消", exact: true }).click();
  for (const missing of [false, true]) {
    const created = await context.request.post(root + "/accounts", { headers, data: {
      requestId: randomUUID(), attemptId: randomUUID(), name: missing ? "缺价验收" : "纯现金验收", brokerName: "验收券商", initialCash: "1000.00",
      commissionRateWan: "3.00", minimumCommission: "5.00", stampTaxRatePct: "0.05",
      initialPositions: missing ? [{ clientRowId: "missing", tsCode: "000002.SZ", openedOn: "2026-09-11", quantity: 100, availableQuantity: 100, costPrice: "10.00" }] : [],
    } });
    assert.equal(created.status(), 201, await created.text());
    const id = (await created.json()).result.account.accountId;
    if (!missing) await waitPublished(id);
    await page.reload();
    await page.getByLabel("交易账户", { exact: true }).selectOption(id);
    await page.getByRole("heading", { name: "当前持仓" }).waitFor();
    if (missing) {
      await page.getByRole("button", { name: "缺价股票", exact: true }).waitFor();
      assert.equal(await page.locator(".ta-positions-table tbody tr").count(), 1);
      assert.match(await summary.innerText(), /—/);
      await page.locator(".ta-position-coverage").waitFor();
    } else {
      assert.equal(await page.locator(".ta-positions-table tbody tr").count(), 0);
      await page.getByRole("group", { name: "持仓视图" }).getByRole("button", { name: "饼图", exact: true }).click();
      await page.getByRole("button", { name: "总资产（含现金）", exact: true }).click();
      assert.equal(await page.locator(".ta-position-pie svg path").count(), 1);
      assert.match(await summary.innerText(), /1,000.00/);
    }
    await page.screenshot({ path: output + (missing ? "-missing.png" : "-cash.png") });
  }
  assert.equal(errors.length, 0, JSON.stringify(errors));
  assert.equal(failed.length, 0, JSON.stringify(failed));
  console.log(JSON.stringify({ passed: true, stocks: 11, accounts: 2, otherMembers: 4, viewChangeRequests, states: ["Ready", "cash", "missing"], bounds }));
} catch (error) {
  const page = context.pages()[0];
  if (page) { await page.screenshot({ path: output + "-failure.png" }); console.error(await page.locator("body").innerText()); }
  throw error;
} finally { await context.close(); await browser.close(); }
