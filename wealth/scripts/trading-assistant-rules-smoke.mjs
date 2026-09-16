// Only a newly created isolated PostgreSQL/Parquet fixture. No real notifications.
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
  const accountResult = await write("/accounts", { name:"规则验收", brokerName:"验收券商", initialCash:"10000.00", commissionRateWan:"2.50", minimumCommission:"5.00", stampTaxRatePct:"0.05", initialPositions:[] });
  const account = accountResult.result.account.accountId;
  await context.addInitScript(token => localStorage.setItem("wealth.auth.access-token", token), session.token);
  const page = await context.newPage(), errors = [], failures = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  page.on("response", r => { if (r.status() >= 400 && r.url().includes("trading-assistant")) failures.push([r.status(), r.url()]); });
  await page.goto(base + "/wealth/market/trading-assistant");
  await page.getByLabel("交易账户", { exact:true }).selectOption(account);
  await page.getByRole("button", { name:"计划与监控", exact:true }).click();
  await page.getByRole("button", { name:"新建交易计划", exact:true }).click();
  let dialog = page.getByRole("dialog").last();
  await dialog.getByRole("combobox", { name:"股票 *" }).fill("000001");
  await dialog.getByRole("option", { name:/测试股票/ }).click();
  await dialog.getByLabel("截止日期", { exact:false }).fill("2026-09-14");
  await dialog.getByLabel("截止时间（北京时间）", { exact:false }).fill("15:00");
  await dialog.getByLabel("价格上限（元）").fill("10.00");
  await dialog.getByRole("checkbox", { name:"当日累计成交量" }).check();
  await dialog.getByLabel("累计成交量（手）").fill("10.00");
  await page.screenshot({ path:output + "-create.png", fullPage:true });
  const buttons = await dialog.locator(".ta-dialog-footer button").evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().width));
  assert.ok(Math.abs(buttons[0] - buttons[1]) < 1);
  await dialog.getByRole("button", { name:"创建计划", exact:true }).click();
  await page.waitForFunction(() => !document.querySelector("dialog[open]"));
  await page.getByRole("button", { name:"查看测试股票详情" }).click();
  await page.getByRole("button", { name:"修改条件", exact:true }).click();
  await context.request.post(base + "/test-rule-clock?at=" + encodeURIComponent("2026-09-11T16:01:00+08:00"));
  dialog = page.getByRole("dialog").last();
  await dialog.getByLabel("价格上限（元）").fill("9.50");
  let revisionRequests = 0;
  await page.route("**/plans/*/condition-revisions", async route => {
    revisionRequests += 1;
    const saved = await route.fetch();
    assert.ok(saved.ok(), await saved.text());
    // The real save committed, but its body is lost. Recovery must GET the
    // original request rather than submit a duplicate condition version.
    await route.fulfill({ status:200, contentType:"application/json", body:"" });
  });
  await dialog.getByRole("button", { name:"保存修改", exact:true }).click();
  await page.waitForFunction(() => document.querySelectorAll("dialog[open]").length === 1);
  await page.getByRole("button", { name:"条件版本历史", exact:true }).click();
  await page.getByRole("heading", { name:"条件版本 2", exact:true }).waitFor();
  assert.equal(revisionRequests, 1);
  assert.equal(await page.getByRole("heading", { name:"条件版本 3", exact:true }).count(), 0);
  await page.getByRole("button", { name:"返回详情", exact:true }).click();
  await page.getByRole("button", { name:"返回列表", exact:true }).click();
  const listResponse = await context.request.get(root + `/plans?accountMode=SINGLE&accountId=${account}`, { headers });
  assert.ok(listResponse.ok(), await listResponse.text());
  const original = (await listResponse.json()).items[0];
  const common = { stockCode:"000001.SZ", deadlineAt:"2026-09-14T15:00:00+08:00", source:"TRADING_ASSISTANT", priceCondition:{operator:"GTE",lower:"20.00"},volumeCondition:null };
  const miss = await write("/plans", { ...common, accountId:account,direction:"SELL" });
  const closed = await write("/plans", { ...common, accountId:account,direction:"BUY" });
  const pendingClose = await (await context.request.post(`${base}/test-pending-rule/${closed.result.ruleId}`)).json();
  // A new page must discover the original RULE-scoped operation from the row,
  // then restore CLOSE, not open a condition editor or silently send again.
  await page.reload();
  await page.getByRole("button", { name:"计划与监控",exact:true }).click();
  await page.locator("button.ta-rule-row").filter({hasText:"买入"}).filter({hasText:"价格 ≥ 20.00"}).click();
  await page.getByRole("heading", { name:"暂时无法确认保存结果",exact:true }).waitFor();
  await context.request.post(`${base}/test-expire-rule/${closed.result.ruleId}/${pendingClose.requestId}`);
  await page.getByRole("button", { name:"重新核对",exact:true }).click();
  await page.getByRole("button", { name:"返回编辑",exact:true }).click();
  await page.getByRole("heading", { name:"关闭这个交易计划？",exact:true }).waitFor();
  assert.equal(await page.getByRole("dialog").last().evaluate(node=>Math.round(node.getBoundingClientRect().width)),520);
  await page.screenshot({path:output+"-close-recovery.png",fullPage:true});
  await page.getByRole("button", { name:"确认关闭",exact:true }).click();
  await page.waitForFunction(()=>document.querySelectorAll("dialog[open]").length===1);
  await page.getByRole("button", { name:"返回列表",exact:true }).click();
  const confirmedClose = await context.request.get(`${root}/plans/${closed.result.ruleId}`, {headers});
  assert.equal((await confirmedClose.json()).ruleStatus,"CLOSED");
  const robot = await (await context.request.post(base + "/test-rule-robot")).json();
  const alert = await write("/alerts", { ...common,robotId:robot.robotId,priceCondition:{operator:"LTE",upper:"10.00"} });
  await context.request.post(base + "/test-rule-clock?at=" + encodeURIComponent("2026-09-14T16:00:00+08:00"));
  let details;
  const until = Date.now() + 45000;
  while (Date.now() < until) {
    details = await Promise.all([["plans",original.ruleId],["plans",miss.result.ruleId],["alerts",alert.result.ruleId]].map(async ([kind,id]) => {
      const response = await context.request.get(`${root}/${kind}/${id}`, { headers }); assert.ok(response.ok(), await response.text()); return response.json();
    }));
    if (details.every(row => row.ruleStatus === "ENDED")) break;
    await new Promise(resolve => setTimeout(resolve,150));
  }
  assert.deepEqual(details.map(row => row.ruleStatus), ["ENDED","ENDED","ENDED"], JSON.stringify(details));
  assert.deepEqual(details.map(row => row.finalResult.triggered), [true,false,true]);
  assert.equal(details[0].finalResult.firstTriggeredAt,"2026-09-14T09:39:00+08:00");
  assert.equal(details[2].notificationSummary.state,"PENDING");
  await page.reload();
  await page.getByRole("button", { name:"计划与监控",exact:true }).click();
  await page.getByLabel("规则状态").selectOption("TRIGGERED");
  await page.waitForFunction(() => document.querySelectorAll("button.ta-rule-row").length === 1);
  await page.getByRole("button", { name:"查看测试股票详情" }).click();
  await page.getByText("条件证据", { exact:true }).waitFor();
  await page.screenshot({ path:output + "-result.png",fullPage:true });
  await page.getByRole("button", { name:"查看验证记录",exact:true }).click();
  await page.getByRole("heading", { name:/第 .* 次/ }).first().waitFor();
  await page.getByRole("button", { name:"返回详情",exact:true }).click();
  await page.getByRole("button", { name:"返回列表",exact:true }).click();
  await page.getByLabel("规则状态").selectOption("ALL");
  await page.waitForFunction(() => document.querySelectorAll("button.ta-rule-row").length === 3);
  assert.equal(await page.getByRole("columnheader",{name:"操作",exact:true}).count(),0);
  const layout = await page.locator(".ta-rule-condition-summary").evaluateAll(nodes => nodes.map(node => ({ whiteSpace:getComputedStyle(node).whiteSpace, height:node.getBoundingClientRect().height })));
  assert.ok(layout.every(row => row.whiteSpace === "nowrap" && row.height < 40));
  await page.screenshot({ path:output + "-list.png",fullPage:true });
  await page.getByRole("button", { name:/独立提醒 1/ }).click();
  await page.getByText("待发送",{exact:true}).waitFor();
  assert.equal(await page.getByRole("columnheader",{name:"方向",exact:true}).count(),0);
  assert.deepEqual(errors,[]); assert.deepEqual(failures,[]);
  console.log(JSON.stringify({ plans:3,alerts:1,result:details.map(row=>row.finalResult.triggered),notification:"PENDING_ONLY",lostRevisionResponse:revisionRequests,layout,errors,failures }));
} catch (error) {
  const page = context.pages().at(-1);
  if (page) { await page.screenshot({ path:output + "-failure.png",fullPage:true }); console.error(JSON.stringify({ dialogs:await page.locator("dialog[open]").allTextContents() })); }
  throw error;
} finally { await context.close(); await browser.close(); }
