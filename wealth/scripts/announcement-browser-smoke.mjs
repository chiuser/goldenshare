// Explicit disposable fixture only. All announcement responses come from real Biz/DAO/runtime.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
const [base, output, playwright] = process.argv.slice(2);
assert.equal(new URL(base).hostname,'127.0.0.1');
const { chromium } = await import(pathToFileURL(playwright).href);
const browser = await chromium.launch({headless:true});
const context = await browser.newContext({viewport:{width:1600,height:1080}});
assert.equal((await (await context.request.get(base+'/test-fixture')).json()).kind,'announcements-isolated-real-api');
await context.addInitScript(()=>localStorage.setItem('wealth.auth.access-token','dc4-test-only'));
const page=await context.newPage();const errors=[],consoleErrors=[],network=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
page.on('response',r=>{if(r.url().includes('/api/'))network.push({path:new URL(r.url()).pathname,status:r.status()});});
const button = name => page.getByRole('button',{name,exact:true});
const tab = name => page.getByRole('tab',{name,exact:true});
const snap = name => page.screenshot({path:`${output}/${name}.png`,fullPage:true});
const ready = () => page.locator('.dc-announcements tbody tr').first().waitFor();
const downloadDate = async () => {await page.getByLabel('下载公告开始日期',{exact:true}).fill('2026-09-30');await page.getByLabel('下载公告结束日期',{exact:true}).fill('2026-09-30');await page.getByLabel('请求间隔（秒）',{exact:true}).fill('0');};
try {
  await page.goto(base+'/wealth/data-center');await button('上市公司公告 本地 查询公司公告，管理 PDF 下载与归档。').waitFor();await snap('home-local');
  await page.getByRole('button',{name:/上市公司公告/}).click();await ready();assert.equal(await page.locator('.dc-announcements th').count(),6);assert.equal(await page.locator('.dc-announcements tbody tr').count(),50);await snap('query-list');
  const external=page.locator('.dc-announcements a').first(); assert.equal(await external.getAttribute('target'),'_blank');assert.equal(await external.getAttribute('rel'),'noopener noreferrer');
  await context.route('https://ann.example/**',r=>r.fulfill({status:200,contentType:'text/html',body:'<p>Isolated source-link destination</p>'}));
  const externalHref=await external.getAttribute('href'); const popupPromise=page.waitForEvent('popup');await external.click();const popup=await popupPromise;await popup.waitForLoadState();assert.equal(popup.url(),externalHref);await popup.close();
  const fixture = await (await context.request.get(base+'/test-fixture')).json();assert.equal(Object.values(fixture.calls).length,0);
  await button('下一页').click();await page.getByText(/显示 51—67 条/).waitFor();await snap('query-page-2');await button('上一页').click();await page.getByText(/显示 1—50 条/).waitFor();
  const company=page.getByLabel('公司名称 / 代码 / 首字母',{exact:true});await company.fill('PAYH');await page.getByRole('option',{name:/平安银行/}).waitFor();await snap('company-candidates');
  await button('查询').click();await page.getByText('请先选择公司',{exact:true}).waitFor();await company.focus();await page.getByRole('option',{name:/平安银行/}).waitFor();await company.press('ArrowDown');await company.press('Enter');await button('查询').click();await page.getByText(/共 44 条公告/).waitFor();await snap('company-selected');
  await page.getByLabel('标题关键词',{exact:true}).fill('董事会');await button('查询').click();await page.getByText(/共 21 条公告/).waitFor();
  await tab('下载管理').click();await button('预览下载范围').waitFor();assert.equal(await page.getByLabel('下载公告开始日期',{exact:true}).inputValue(),'');assert.equal(await page.getByLabel('请求间隔（秒）',{exact:true}).inputValue(),'5');assert.equal(await page.getByLabel('归档位置',{exact:true}).isDisabled(),true);assert.equal(await button('预览下载范围').isDisabled(),true);await snap('downloads-empty');
  await page.goBack();await tab('公告查询').waitFor();await page.waitForFunction(()=>document.querySelector('[role="tab"][aria-selected="true"]')?.textContent==='公告查询');assert.equal(await page.getByLabel('标题关键词',{exact:true}).inputValue(),'董事会');
  await page.goForward();await button('预览下载范围').waitFor();checks.push({routeHistory:'back-forward-preserves-query-draft'});
  await page.getByLabel('下载公告开始日期',{exact:true}).fill('2026-10-01');await page.getByLabel('下载公告结束日期',{exact:true}).fill('2026-09-30');await snap('downloads-reversed');assert.equal(await button('预览下载范围').isDisabled(),true);
  await downloadDate();await snap('downloads-valid');await button('预览下载范围').click();await button('开始下载').waitFor();await snap('preview');
  const preview=await (await context.request.get(base+'/test-fixture')).json();const posted=preview.requests.filter(r=>r.path.endsWith('/previews')&&r.method==='POST');assert.deepEqual(posted.at(-1).body,{startDate:'2026-09-30',endDate:'2026-09-30',intervalSeconds:0});assert.equal(Object.values(preview.calls).length,0);
  await button('开始下载').click();await button('停止任务').waitFor();await snap('downloading');
  await button('停止任务').click();await page.getByRole('dialog').waitFor();await snap('stop-dialog');await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),0);
  await button('停止任务').click();await button('确认停止').click();await button('继续未完成项').waitFor();await snap('stopped');
  const runId = new URL(page.url()).searchParams.get('runId');assert.ok(runId);
  await tab('公告查询').click();assert.equal(await page.getByLabel('标题关键词',{exact:true}).inputValue(),'董事会');await tab('下载管理').click();await button('继续未完成项').waitFor();await button('继续未完成项').click();
  await page.getByRole('heading',{name:'已结束，存在失败项',exact:true}).waitFor({timeout:30000});await button('重试全部失败项').waitFor();await snap('partial-failed');
  assert.ok((await page.locator('.dc-progress[aria-valuenow="100"]').count())>0);await page.locator('.dc-files summary').last().click();await snap('failure-expanded');
  await page.locator('.dc-files').getByRole('button',{name:'重试',exact:true}).first().click();await page.getByRole('heading',{name:'全部成功',exact:true}).waitFor({timeout:20000});await snap('single-retry-completed');
  await page.goto(base+`/wealth/data-center/announcements?tab=downloads&runId=${runId}`);await button('重试全部失败项').waitFor();await button('重试全部失败项').click();await page.getByRole('heading',{name:'全部成功',exact:true}).waitFor({timeout:20000});await button('查看文件结果').click();await snap('related-results');
  const final = await (await context.request.get(base+'/test-fixture')).json();const runPosts=final.requests.filter(r=>r.method==='POST'&&r.path.endsWith('/runs'));assert.equal(runPosts.length,1);
  const retries=final.requests.filter(r=>r.path.endsWith('/retries'));assert.equal(retries.length,2);assert.equal(retries[0].body.scope,'singleFailed');assert.equal(retries[1].body.scope,'allFailed');
  const original=await (await context.request.get(base+`/api/v1/wealth/data-center/announcements/runs/${runId}`)).json();assert.equal(original.total,64);assert.equal(original.failed,2);assert.equal(original.unresolvedFailureCount,0);
  const reports=final.requests.filter(r=>r.path.endsWith('/previews')||r.path.endsWith('/runs')||r.path.endsWith('/retries'));checks.push({realOriginal:original,commands:reports});
  await tab('公告查询').click();await button('重置').click();await ready();assert.ok(await page.getByText('已下载',{exact:true}).count()>0);await page.getByLabel('下载状态',{exact:true}).selectOption('downloaded');await button('查询').click();await page.getByText(/共 65 条公告/).waitFor();await snap('query-downloaded');
  await page.getByLabel('标题关键词',{exact:true}).fill('不存在的标题关键词');await button('查询').click();await page.getByText('没有符合条件的公告',{exact:true}).waitFor();await snap('query-empty');await button('清除筛选').click();await ready();
  for(const width of [1600,1512,1460,1366]){await page.setViewportSize({width,height:1080});const geometry=await page.locator('.dc-panel').evaluateAll(nodes=>nodes.map(n=>({width:n.clientWidth,overflow:n.scrollWidth>n.clientWidth})));assert.ok(geometry.every(g=>!g.overflow));checks.push({width,geometry});await snap(`query-${width}`);}
  await page.setViewportSize({width:1600,height:1080});
  await page.goto(base+'/wealth/data-center/announcements?tab=unknown');await ready();assert.equal(new URL(page.url()).searchParams.get('tab'),'query');
  await page.goto(base+'/wealth/data-center/announcements?tab=downloads&runId=00000000-0000-4000-8000-000000000000');await page.getByText(/任务暂不可获取/).waitFor();await snap('unknown-run');checks.push({missingRun:'explicit-unavailable-not-idle'});
  for(const kind of ['preparing','stopping','interrupted','volume-blocked','remote-blocked','retry','single-retry']){
    const scenario=await (await context.request.post(base+'/test-visual-state/'+kind)).json();assert.equal(scenario.evidence,'synthetic-ledger-visual-only');
    await page.goto(base+`/wealth/data-center/announcements?tab=downloads&runId=${scenario.runId}`);await page.getByRole('heading',{name:kind==='preparing'?'正在准备':kind==='stopping'?'停止中':kind==='interrupted'?'已中断':kind==='retry'?'正在重试原任务失败项':kind==='single-retry'?'正在重试单个失败文件':'已阻断',exact:true}).waitFor();
    if(kind==='preparing')assert.equal(await page.getByRole('progressbar').getAttribute('aria-valuenow'),null);
    if(kind==='stopping')assert.equal(await button('停止中…').isDisabled(),true);
    if(kind==='remote-blocked'){assert.equal(await button('继续未完成项').count(),0);await button('重新检查来源').waitFor();}
    await snap('visual-'+kind);checks.push({visualState:kind,source:'synthetic-durable-ledger-real-api'});
  }
  await page.goto(base+'/wealth/data-center/announcements');await ready();
  await context.request.post(base+'/test-environment/unplug');await button('刷新列表').click();await page.getByText(/下载状态暂无法核验/).waitFor();assert.equal(await page.locator('.dc-announcements tbody').getByText('未下载',{exact:true}).count(),0);await snap('query-unplugged');await context.request.post(base+'/test-environment/plug');
  await context.request.post(base+'/test-environment/source-error');await button('刷新列表').click();await page.getByText(/列表暂不可获取/).waitFor();await snap('query-source-error');
  await context.request.post(base+'/test-environment/prod');await page.goto(base+'/wealth/data-center');await page.getByText('当前暂无可用数据模块',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:/上市公司公告/}).count(),0);await snap('home-prod');
  assert.deepEqual(errors,[]);assert.ok(consoleErrors.every(v=>/503|404/.test(v)),consoleErrors.join('\n'));
  assert.ok(network.filter(r=>r.status===404).every(r=>r.path.endsWith('/runs/00000000-0000-4000-8000-000000000000')));
  await writeFile(`${output}/browser-evidence.json`,JSON.stringify({errors,consoleErrors,network,checks},null,2));
  console.log(JSON.stringify({status:'passed',checks:checks.length,consoleErrors,sourceSiteRequests:0}));
}catch(e){await snap('failure');throw e;}finally{await browser.close();}
