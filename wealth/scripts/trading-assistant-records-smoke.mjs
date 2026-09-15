// Only the newly created isolated M3 fixture is accepted; no production writes.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
const [base, output, modulePath] = process.argv.slice(2);
assert.equal(new URL(base).hostname, "127.0.0.1");
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 1080 } });
try {
  const session = await (await context.request.get(base + "/test-session?user_id=1")).json();
  assert.equal(session.fixture, "trading-assistant-isolated");
  const root = base + "/api/v1/wealth/market/trading-assistant", headers = { Authorization: "Bearer " + session.token };
  async function write(path, data) {
    const response = await context.request.post(root + path, { headers, data: { requestId: randomUUID(), attemptId: randomUUID(), ...data } });
    assert.ok(response.ok(), await response.text()); return response.json();
  }
  const created = await write("/accounts", { name: "记录验收", brokerName: "验收券商", initialCash: "10000.00", commissionRateWan: "0.00", minimumCommission: "0.00", stampTaxRatePct: "0.00",
    initialPositions: [{ clientRowId: "one", tsCode: "000001.SZ", openedOn: "2026-09-10", quantity: 1000, availableQuantity: 1000, costPrice: "10.00" }] });
  const account = created.result.account.accountId;
  for (const price of ["12.00", "13.00"]) await write(`/accounts/${account}/trades`, { tsCode: "000001.SZ", direction: "SELL", tradeDate: "2026-09-11", price, quantity: 100, note: "逐笔保留" });
  for (let i = 0; i < 23; i++) await write(`/accounts/${account}/cash-flows`, { direction: "IN", occurredOn: "2026-09-11", amount: "10.00", note: `资金样本 ${i}` });
  let status;
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    status = await (await context.request.get(`${root}/accounts/${account}/calculation-status`, { headers })).json();
    if (status.stage === "PUBLISHED") break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(status.stage, "PUBLISHED", JSON.stringify(status));
  await context.addInitScript(token => localStorage.setItem("wealth.auth.access-token", token), session.token);
  const page = await context.newPage(), errors = [], failures = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  page.on("response", r => { if (r.status() >= 400 && r.url().includes("trading-assistant")) failures.push([r.status(), r.url()]); });
  await page.goto(base + "/wealth/market/trading-assistant");
  await page.getByLabel("交易账户", { exact: true }).selectOption(account);
  await page.getByRole("button", { name: "收益分析", exact: true }).click();
  await page.getByRole("button", { name: "记录", exact: true }).click();
  const rows = page.locator(".ta-record-table-scroll tbody tr"), cards = page.getByLabel("本月记录摘要");
  await rows.first().waitFor(); assert.equal(await rows.count(), 2);
  assert.match(await cards.innerText(), /\+500.00/);
  await page.getByRole("button", { name: "当日汇总", exact: true }).click();
  await page.getByRole("button", { name: "查看 2 笔原始成交" }).waitFor(); assert.equal(await rows.count(), 1);
  await page.getByRole("button", { name: "查看 2 笔原始成交" }).click();
  await page.getByRole("button", { name: "返回上级记录" }).waitFor();
  await page.waitForFunction(() => document.querySelectorAll(".ta-record-table-scroll tbody tr").length === 2);
  await page.getByRole("button", { name: "返回上级记录" }).click();
  await page.getByRole("button", { name: "闭环交易", exact: true }).click();
  await page.getByRole("button", { name: /查看第 .*轮全部闭环/ }).waitFor();
  assert.equal(await rows.count(), 2); assert.match(await page.locator(".ta-record-detail").innerText(), /当日结束持仓/);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: output + "-closed.png", fullPage: true });
  await page.getByRole("button", { name: /查看第 .*轮全部闭环/ }).click();
  await page.getByRole("button", { name: "返回上级记录" }).waitFor();
  await page.waitForFunction(() => document.querySelectorAll(".ta-record-table-scroll tbody tr").length === 2);
  await page.getByRole("button", { name: "资金流水", exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll(".ta-record-table-scroll tbody tr").length === 20);
  assert.equal(await page.getByRole("button", { name: "上一页", exact: true }).isDisabled(), true);
  const totals = await cards.innerText();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll(".ta-record-table-scroll tbody tr").length === 3);
  assert.equal(await cards.innerText(), totals);
  assert.equal(await page.getByRole("button", { name: "下一页", exact: true }).isDisabled(), true);
  assert.doesNotMatch(await page.locator(".ta-records").innerText(), /当日现金余额|初始化现金|[¥￥$]/);
  await page.getByRole("button", { name: "更正流水", exact: true }).waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: output + "-cash.png", fullPage: true });
  await page.getByRole("button", { name: "更正流水", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  assert.match(await page.getByRole("dialog").innerText(), /更正/);
  await page.getByLabel("金额（元）", { exact: false }).fill("15.00");
  await page.getByRole("button", { name: "核对更正", exact: true }).click();
  await page.getByRole("button", { name: "确认更正", exact: true }).click();
  await page.getByRole("heading", { name: "资金流水 · 原始收支", exact: true }).waitFor();
  await page.getByRole("dialog").getByRole("button", { name: "关闭", exact: true }).last().click();
  await page.waitForFunction(() => !document.querySelector("dialog[open]"));
  await page.waitForFunction(() => document.querySelector('[aria-label="本月记录摘要"]')?.textContent.includes("235.00"));
  assert.equal(await page.getByRole("button", { name: "资金流水", exact: true }).getAttribute("aria-pressed"), "true");
  await page.waitForFunction(() => document.querySelectorAll(".ta-record-table-scroll tbody tr").length === 20);
  assert.equal(errors.length, 0, JSON.stringify(errors)); assert.equal(failures.length, 0, JSON.stringify(failures));
  const bulk = await write("/accounts", { name: "闭环分页验收", brokerName: "验收券商", initialCash: "0.00", commissionRateWan: "0.00", minimumCommission: "0.00", stampTaxRatePct: "0.00",
    initialPositions: [{ clientRowId: "bulk", tsCode: "000001.SZ", openedOn: "2026-09-10", quantity: 1000, availableQuantity: 1000, costPrice: "10.00" }] });
  const bulkId = bulk.result.account.accountId;
  for (let i = 0; i < 23; i++) await write(`/accounts/${bulkId}/trades`, { tsCode: "000001.SZ", direction: "SELL", tradeDate: "2026-09-11", price: "12.00", quantity: 10 });
  const bulkDeadline = Date.now() + 30000;
  let bulkStatus;
  while (Date.now() < bulkDeadline) {
    bulkStatus = await (await context.request.get(`${root}/accounts/${bulkId}/calculation-status`, { headers })).json();
    if (bulkStatus.stage === "PUBLISHED") break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(bulkStatus.stage, "PUBLISHED", JSON.stringify(bulkStatus));
  async function closed(query) {
    const response = await context.request.get(`${root}/records/closed-trades?${new URLSearchParams(query)}`, { headers });
    assert.ok(response.ok(), await response.text()); return response.json();
  }
  const range = { accountMode: "SINGLE", accountId: bulkId, stockMode: "ALL", requestedStartDate: "2026-09-01", requestedEndDate: "2026-09-11", limit: "20" };
  const first = await closed(range), next = await closed({ ...range, readContext: first.readContext.contextToken, cursor: first.nextCursor });
  assert.deepEqual([first.items.length, next.items.length], [20, 3]);
  assert.equal(new Set([...first.items, ...next.items].map(r => r.tradeId)).size, 23);
  assert.equal(first.summary.closedProfitAmount, "460.00"); assert.deepEqual(next.summary, first.summary);
  const roundQuery = { accountId: bulkId, roundId: first.items[0].roundRef.roundId, limit: "20", readContext: first.readContext.contextToken };
  const roundFirst = await closed(roundQuery), roundNext = await closed({ ...roundQuery, cursor: roundFirst.nextCursor });
  assert.deepEqual([roundFirst.items.length, roundNext.items.length], [20, 3]);
  assert.deepEqual(roundFirst.summary, first.summary);
  assert.deepEqual([...roundFirst.items, ...roundNext.items].map(r => r.tradeId), [...first.items, ...next.items].reverse().map(r => r.tradeId));
  await page.reload();
  await page.getByLabel("交易账户", { exact:true }).selectOption(bulkId);
  await page.getByRole("button", { name:"收益分析",exact:true }).click();
  await page.getByRole("button", { name:"记录",exact:true }).click();
  await page.getByRole("button", { name:"闭环交易",exact:true }).click();
  await page.waitForFunction(()=>document.querySelectorAll(".ta-record-table-scroll tbody tr").length===20);
  const completeSummary=await page.getByLabel("当前闭环范围汇总").innerText();
  assert.match(completeSummary,/23 笔 · 收益 \+460.00/);
  await page.getByRole("button", { name:"下一页",exact:true }).click();
  await page.waitForFunction(()=>document.querySelectorAll(".ta-record-table-scroll tbody tr").length===3);
  assert.equal(await page.getByLabel("当前闭环范围汇总").innerText(),completeSummary);
  assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
  console.log(JSON.stringify({ trades: 2, groups: 1, closures: 2, cashPages: [20, 3], closedPages: [20, 3], closedTotal: "460.00", errors, failures }));
} catch (error) {
  const page = context.pages().at(-1);
  if (page) { await page.screenshot({ path: output + "-failure.png", fullPage: true }); console.error(JSON.stringify({ dialogs: await page.locator("dialog[open]").allTextContents() })); }
  throw error;
} finally { await context.close(); await browser.close(); }
