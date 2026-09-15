// Only a newly created isolated M3 fixture; never a production URL.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
const [base,output,modulePath] = process.argv.slice(2);
assert.equal(new URL(base).hostname,"127.0.0.1");
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({ headless:true });
const context = await browser.newContext({ viewport:{ width:1600,height:1080 } });
try {
  const session = await (await context.request.get(base+"/test-session")).json();
  assert.equal(session.fixture,"trading-assistant-isolated");
  const root = base+"/api/v1/wealth/market/trading-assistant", headers = { Authorization:"Bearer "+session.token };
  async function write(path,data) {
    const response = await context.request.post(root+path,{ headers,data:{ requestId:randomUUID(),attemptId:randomUUID(),...data } });
    assert.ok(response.ok(),await response.text()); return response.json();
  }
  const created = await write("/accounts",{ name:"收益验收",brokerName:"验收券商",initialCash:"1000.00",commissionRateWan:"0.00",minimumCommission:"0.00",stampTaxRatePct:"0.00",
    initialPositions:[{ clientRowId:"one",tsCode:"000001.SZ",openedOn:"2026-09-10",quantity:1000,availableQuantity:1000,costPrice:"10.00" }] });
  const account = created.result.account.accountId;
  await write(`/accounts/${account}/trades`,{ tsCode:"000001.SZ",direction:"SELL",tradeDate:"2026-09-11",price:"12.00",quantity:1000 });
  let status; const until = Date.now()+30000;
  while(Date.now()<until) {
    status = await (await context.request.get(`${root}/accounts/${account}/calculation-status`,{ headers })).json();
    if(status.stage==="PUBLISHED") break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.equal(status.stage,"PUBLISHED",JSON.stringify(status));
  await context.addInitScript(token=>localStorage.setItem("wealth.auth.access-token",token),session.token);
  const page = await context.newPage(), errors=[],failures=[],requests=[];
  page.on("pageerror",error=>errors.push(error.message));
  page.on("console",message=>{if(message.type()==="error") errors.push(message.text());});
  page.on("response",response=>{if(response.status()>=400&&response.url().includes("trading-assistant")) failures.push([response.status(),response.url()]);});
  page.on("request",request=>{if(request.url().includes("/returns/")) requests.push(request.url());});
  await page.goto(base+"/wealth/market/trading-assistant");
  await page.getByLabel("交易账户",{ exact:true }).selectOption(account);
  await page.getByRole("button",{ name:"收益分析",exact:true }).click();
  await page.getByRole("img",{ name:"期间收益率曲线" }).waitFor();
  await page.getByRole("button",{ name:"查看已结束整轮 · 1 轮" }).waitFor();
  const aligned = await page.evaluate(()=>{
    const summary=document.querySelector(".ta-return-summary").getBoundingClientRect();
    const panels=document.querySelector(".ta-return-columns").getBoundingClientRect();
    return Math.abs(summary.left-panels.left)<1 && Math.abs(summary.right-panels.right)<1;
  });
  assert.equal(aligned,true);
  const summary=page.getByLabel("当前与本月收益摘要");
  assert.match(await summary.innerText(),/2,000.00/);
  await page.getByRole("button",{ name:"全部",exact:true }).click();
  await page.getByText("区间：2026-09-10—2026-09-11",{ exact:false }).waitFor();
  await page.getByRole("button",{ name:"查看已结束整轮 · 1 轮" }).waitFor();
  await page.screenshot({ path:output+"-curve.png",fullPage:true });
  await page.getByRole("button",{ name:"查看已结束整轮 · 1 轮" }).click();
  await page.locator(".ta-completed-rows button").click();
  await page.getByRole("dialog").getByText("整轮收益",{ exact:true }).waitFor();
  assert.match(await page.getByRole("dialog").innerText(),/20.00%/);
  assert.equal(await page.getByRole("dialog").evaluate(node=>Math.round(node.getBoundingClientRect().width)),640);
  await page.screenshot({ path:output+"-closed-round.png",fullPage:true });
  await page.getByRole("button",{ name:"查看本轮闭环记录",exact:true }).click();
  await page.locator(".ta-record-table-scroll tbody tr").first().waitFor();
  assert.match(await page.locator(".ta-records").innerText(),/2,000.00/);
  assert.match(await page.getByLabel("当前闭环范围汇总").innerText(),/本轮闭环 1 笔 · 收益 \+2,000.00/);
  await page.getByRole("button",{ name:"返回整轮列表",exact:true }).click();
  await page.getByRole("button",{ name:"返回复盘",exact:true }).click();
  await page.getByText("区间：2026-09-10—2026-09-11",{ exact:false }).waitFor();
  await page.getByRole("button",{ name:"日历",exact:true }).click();
  await page.getByRole("button",{ name:"2026-09-10",exact:true }).waitFor();
  assert.equal(await page.locator(".ta-return-day").count(),25);
  assert.match(await page.getByRole("button",{ name:"2026-09-10",exact:true }).innerText(),/2,000.00/);
  assert.equal((await page.getByRole("button",{ name:"2026-09-14",exact:true }).innerText()).trim(),"14");
  const before=requests.length;
  await page.getByRole("button",{ name:"收益率",exact:true }).click();
  assert.match(await page.getByRole("button",{ name:"2026-09-10",exact:true }).innerText(),/20.00%/);
  assert.equal(requests.length,before);
  await page.locator(".ta-return-columns > aside .ta-return-day-core").waitFor();
  await page.screenshot({ path:output+"-calendar.png",fullPage:true });
  await page.getByRole("button",{ name:"2026-09-11",exact:true }).click();
  await page.getByRole("dialog").getByText("当天股票收益贡献 · 1 只").waitFor();
  assert.match(await page.getByRole("dialog").innerText(),/0.00/);
  await page.screenshot({ path:output+"-day.png",fullPage:true });
  await page.getByRole("dialog").getByRole("button",{ name:"当天成交",exact:true }).click();
  await page.locator(".ta-record-table-scroll tbody tr").first().waitFor();
  assert.match(await page.locator(".ta-record-scope").last().innerText(),/2026-09-11—2026-09-11/);
  await page.getByRole("button",{ name:"返回收益日历",exact:true }).click();
  assert.equal(await page.getByRole("button",{ name:"2026-09-11",exact:true }).getAttribute("aria-pressed"),"true");
  const ongoing = await write("/accounts",{ name:"进行中收益验收",brokerName:"验收券商",initialCash:"1000.00",commissionRateWan:"0.00",minimumCommission:"0.00",stampTaxRatePct:"0.00",
    initialPositions:[{ clientRowId:"one",tsCode:"000001.SZ",openedOn:"2026-09-10",quantity:1000,availableQuantity:1000,costPrice:"10.00" }] });
  const ongoingAccount=ongoing.result.account.accountId;
  await write(`/accounts/${ongoingAccount}/trades`,{ tsCode:"000001.SZ",direction:"SELL",tradeDate:"2026-09-11",price:"12.00",quantity:400 });
  const openUntil=Date.now()+30000;
  do {
    status=await (await context.request.get(`${root}/accounts/${ongoingAccount}/calculation-status`,{ headers })).json();
    if(status.stage==="PUBLISHED") break;
    await new Promise(resolve=>setTimeout(resolve,100));
  } while(Date.now()<openUntil);
  assert.equal(status.stage,"PUBLISHED",JSON.stringify(status));
  await page.reload();
  await page.getByLabel("交易账户",{ exact:true }).selectOption(ongoingAccount);
  await page.getByRole("button",{ name:"收益分析",exact:true }).click();
  await page.getByRole("button",{ name:"记录",exact:true }).click();
  await page.getByRole("button",{ name:"闭环交易",exact:true }).click();
  await page.getByRole("button",{ name:"查看所属轮次",exact:true }).click();
  await page.getByRole("dialog").getByText("当前持仓 600 股 · 可卖 600 股",{ exact:true }).waitFor();
  assert.match(await page.getByRole("dialog").innerText(),/第 1 轮/);
  const feeLayout=await page.getByRole("dialog").getByLabel("预计卖出费用").evaluate(node=>{
    const title=node.querySelector("h3"),value=node.querySelector("strong"),note=node.querySelector("small");
    return { title:getComputedStyle(title).fontSize,value:getComputedStyle(value).fontSize,note:getComputedStyle(note).fontSize,
      aligned:Math.abs(title.getBoundingClientRect().left-value.getBoundingClientRect().left)<1 && getComputedStyle(value).textAlign!=="center" };
  });
  assert.deepEqual(feeLayout,{ title:"14px",value:"28px",note:"13px",aligned:true });
  await page.screenshot({ path:output+"-open-round.png",fullPage:true });
  await page.getByRole("dialog").getByRole("button",{ name:"查看本轮闭环记录",exact:true }).click();
  await page.getByText(/整轮闭环 · 完整轮次日期/).waitFor();
  assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
  console.log(JSON.stringify({ account,errors,failures,requests:requests.length,screenshots:output }));
} finally { await context.close();await browser.close(); }
