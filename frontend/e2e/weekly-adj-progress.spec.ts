import { expect, test } from "@playwright/test";
import { createTaskRunView, installApiMocks, setAdminSession } from "./support/smoke-fixtures";

test("weekly refresh activity, committed progress and unavailable ETA follow polling", async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("requestfailed", request => failedRequests.push(request.url()));
  await setAdminSession(page);
  await installApiMocks(page, "task-detail");
  let requestCount = 0;
  await page.route("**/api/v1/ops/task-runs/1/view", async route => {
    const done = Math.min(requestCount++, 1);
    const view = createTaskRunView({ id: 1, title: "股票周线行情（复权）", resource_key: "stk_period_bar_adj_week",
      status: "running", unit_total: 2, unit_done: done, progress_percent: done * 50, rows_saved: done * 5559 });
    const weekly = { stage: done ? "刷新股票历史" : "下载新周", updated_at: "2026-10-10T00:00:05Z",
      ts_code: done ? "000001.SZ" : null, trade_date: done ? null : "20261009",
      start_date: done ? "20100101" : null, end_date: done ? "20261009" : null,
      unit_done: done, unit_total: 2, page_number: 1, rows_preserved: 3, eta: "unavailable" };
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ ...view, progress: { ...view.progress, weekly_adj_progress: weekly } }) });
  });
  await page.setViewportSize({ width: 1024, height: 1200 });
  const started = Date.now();
  await page.goto("/app/ops/tasks/1");
  await expect(page.getByText("复权周线：下载新周")).toBeVisible();
  await expect(page.getByText("复权周线：刷新股票历史")).toBeVisible({ timeout: 25000 });
  await expect(page.getByText(/000001.SZ｜20100101 至 20261009/)).toBeVisible();
  await expect(page.getByText("完成 1/2 单元｜保留未刷新 3 条")).toBeVisible();
  await expect(page.getByText(/最近更新 .*预计完成：暂无法估算/)).toBeVisible();
  expect(Date.now() - started).toBeLessThan(30000);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
