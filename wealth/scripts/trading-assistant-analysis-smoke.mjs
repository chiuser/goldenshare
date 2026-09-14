// Fresh isolated local fixture only. Seed source facts, write actual commands, wait for M3.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
const [base, output, playwrightModule] = process.argv.slice(2);
assert.equal(new URL(base).hostname, "127.0.0.1");
const { chromium } = await import(pathToFileURL(playwrightModule).href);
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 1080 } });
try {
  const session = await (await context.request.get(base + "/test-session?user_id=1")).json();
  assert.equal(session.fixture, "trading-assistant-isolated");
  const root = base + "/api/v1/wealth/market/trading-assistant", headers = { Authorization: "Bearer " + session.token };
  async function create(name, initialPositions, stage = "PUBLISHED") {
    const created = await context.request.post(root + "/accounts", { headers, data: { requestId: randomUUID(), attemptId: randomUUID(),
      name, brokerName: "验收券商", initialCash: "1000.00", commissionRateWan: "0.00", minimumCommission: "0.00", stampTaxRatePct: "0.00", initialPositions } });
    assert.equal(created.status(), 201, await created.text());
    const id = (await created.json()).result.account.accountId;
    let last;
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      last = await (await context.request.get(`${root}/accounts/${id}/calculation-status`, { headers })).json();
      if (last.stage === stage) return id;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error("M3 publication timeout " + JSON.stringify(last));
  }
  const initial = code => ({ clientRowId: code, tsCode: code, openedOn: "2026-09-10", quantity: 100, availableQuantity: 100, costPrice: "10.00" });
  const main = await create("持仓分析验收", Array.from({ length: 11 }, (_, i) => initial(`${1201 + i}`.padStart(6, "0") + ".SZ")));
  const cash = await create("分析纯现金", []);
  const missing = await create("分析缺行情", [initial("000002.SZ")], "WAITING_DATA");
  await context.addInitScript(token => localStorage.setItem("wealth.auth.access-token", token), session.token);
  const page = await context.newPage(), errors = [], requests = [], failures = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("request", request => { if (request.url().includes("/positions")) requests.push(request.url()); });
  page.on("response", response => { if (response.status() >= 400 && response.url().includes("trading-assistant")) failures.push(response.status()); });
  await page.goto(base + "/wealth/market/trading-assistant");
  await page.getByLabel("交易账户", { exact: true }).selectOption(main);
  await page.getByRole("heading", { name: /^当前持仓/ }).waitFor();
  const toolbar = await page.locator(".ta-position-toolbar").evaluate(node => ({ scroll: node.scrollWidth, client: node.clientWidth }));
  assert.ok(toolbar.scroll <= toolbar.client + 1, JSON.stringify(toolbar));
  await page.getByRole("button", { name: "持仓分析", exact: true }).click();
  await page.locator(".ta-analysis-industry").first().waitFor();
  assert.equal(await page.locator(".ta-analysis-industry").count(), 11);
  const analysis = page.getByRole("region", { name: "持仓分析", exact: true });
  assert.match(await analysis.innerText(), /29.46%/);
  assert.match(await analysis.innerText(), /49.11%/);
  assert.match(await analysis.innerText(), /未分类/);
  assert.match(await analysis.innerText(), /盈利 5 只 · 亏损 3 只 · 持平 3 只/);
  assert.match(await analysis.innerText(), /盈利合计 \+500.00 \/ 亏损合计 -300.00/);
  assert.doesNotMatch(await analysis.innerText(), /[¥￥$]/);
  const bounds = await page.locator(".ta-analysis-metrics .ta-position-metric").evaluateAll(nodes => nodes.map(node => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width }; }));
  const panels = await page.locator(".ta-analysis-panels").boundingBox();
  assert.equal(new Set(bounds.map(row => row.width)).size, 1);
  assert.equal(new Set(bounds.map(row => row.y)).size, 1);
  assert.equal(bounds[1].x, bounds[0].x + bounds[0].width, "R5-A cards must be contiguous");
  assert.equal(await page.locator(".ta-analysis-metrics strong").first().evaluate(node => getComputedStyle(node).fontSize), "28px");
  const buttons = await page.getByRole("group", { name: "贡献口径" }).getByRole("button").evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().width));
  assert.equal(buttons[0], buttons[1]);
  assert.equal(bounds[0].x, panels.x);
  assert.ok(Math.abs(bounds[3].x + bounds[3].width - panels.x - panels.width) < 1);
  await page.screenshot({ path: output + "-cumulative.png" });
  const before = requests.length;
  await page.getByRole("button", { name: "当日", exact: true }).click();
  assert.match(await analysis.innerText(), /上涨贡献 5 只 · 下跌贡献 3 只 · 持平 3 只/);
  await page.screenshot({ path: output + "-daily.png" });
  await page.getByRole("button", { name: "当前持仓累计", exact: true }).click();
  assert.equal(requests.length, before, "Contribution switch must not refetch");
  for (const [account, label] of [[cash, "cash"], [missing, "missing"]]) {
    await page.getByLabel("交易账户", { exact: true }).selectOption(account);
    await page.locator(".ta-analysis-metrics").waitFor();
    if (label === "cash") assert.match(await analysis.innerText(), /暂无当前持仓/);
    else { assert.match(await analysis.innerText(), /待计算 1 只/); assert.match(await analysis.innerText(), /盈利合计 —/); }
    await page.screenshot({ path: output + `-${label}.png` });
  }
  await page.getByRole("button", { name: "返回持仓列表", exact: true }).click();
  await page.getByRole("heading", { name: /^当前持仓/ }).waitFor();
  assert.equal(errors.length, 0, JSON.stringify(errors));
  assert.equal(failures.length, 0, JSON.stringify(failures));
  console.log(JSON.stringify({ industries: 11, switchRequests: 0, cards: bounds, errors, failures }));
} finally { await context.close(); await browser.close(); }
