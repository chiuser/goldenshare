// Real API regression on disposable PG/Parquet; no source-site or formal writes.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
const [base, output, playwright, executablePath] = process.argv.slice(2);
assert.equal(new URL(base).hostname, '127.0.0.1');
const { chromium } = await import(pathToFileURL(playwright).href);
const browser = await chromium.launch({ headless: true, executablePath });
try {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1080 } });
  await context.addInitScript(() => localStorage.setItem('wealth.auth.access-token', 'isolated-query-regression'));
  const page = await context.newPage(); const errors = [], consoleErrors = [], network = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('response', r => { if (r.url().includes('/api/')) network.push({ path: new URL(r.url()).pathname, query: new URL(r.url()).search, status: r.status() }); });
  await page.goto(base + '/wealth/data-center/announcements');
  await page.getByText(/本地公告已更新至 2026-10-07，已展示此前公告/).waitFor();
  const input = page.getByRole('combobox', { name: '公司名称 / 代码 / 首字母' });
  await input.pressSequentially('payh', { delay: 60 });
  await page.getByRole('option', { name: /平安银行/ }).waitFor();
  await page.screenshot({ path: output + '/lowercase-candidates.png', fullPage: true });
  await page.getByRole('option', { name: /平安银行/ }).click();
  await page.getByLabel('公告结束日期', { exact: true }).fill('2026-09-30');
  assert.match(await input.inputValue(), /000001.SZ/);
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await page.getByText(/共 2 条公告/).waitFor();
  assert.equal(await page.locator('.dc-announcements tbody tr').count(), 2);
  assert.match(await page.locator('.dc-announcements tbody').innerText(), /000001.SZ/);
  assert.equal(await page.getByText('列表暂不可获取').count(), 0);
  await page.screenshot({ path: output + '/historical-query.png', fullPage: true });
  // Editing the selected company still requires explicit selection; keyboard works.
  await input.fill('payh');
  await page.getByRole('option', { name: /平安银行/ }).waitFor();
  await input.press('ArrowDown'); await input.press('Enter');
  assert.match(await input.inputValue(), /000001.SZ/);
  await page.getByLabel('公告结束日期', { exact: true }).fill('2026-10-08');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await page.getByText(/本地公告已更新至 2026-10-07，已展示此前公告/).waitFor();
  assert.equal(await page.locator('.dc-announcements tbody tr').count(), 2);
  assert.equal(await page.getByLabel('公告结束日期', { exact: true }).inputValue(), '2026-10-08');
  assert.equal(await page.getByText('列表暂不可获取').count(), 0);
  assert.equal(await page.locator('.dc-notice.danger').count(), 0);
  await page.screenshot({ path: output + '/tail-adjusted-query.png', fullPage: true });
  await page.getByRole('button', { name: '刷新列表', exact: true }).click();
  await page.getByText(/本地公告已更新至 2026-10-07，已展示此前公告/).waitFor();
  assert.equal(await page.getByLabel('公告结束日期', { exact: true }).inputValue(), '2026-10-08');
  // Leading or internal gaps must still be reported, never expanded or skipped.
  await page.getByLabel('公告开始日期', { exact: true }).fill('2026-09-29');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await page.getByText(/本地尚未同步 2026-09-29 的公告数据/).waitFor();
  assert.equal(await page.locator('.dc-announcements tbody tr').count(), 0);
  assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []);
  assert.equal(network.filter(r => r.path.includes('/data-center/') && r.status >= 400).length, 0);
  await writeFile(output + '/browser-evidence.json', JSON.stringify({ lowercaseCandidates: true, selectionSurvivesDateChange: true, historicalRows: 2, tailAdjusted: true, requestedEndDatePreserved: true, leadingGapStillErrors: true, keyboardSelection: true, errors, consoleErrors, network }, null, 2));
} finally { await browser.close(); }
