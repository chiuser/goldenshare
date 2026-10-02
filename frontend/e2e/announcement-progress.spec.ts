import { expect, test } from "@playwright/test";
import { createTaskRunView, installApiMocks, setAdminSession } from "./support/smoke-fixtures";

test("公告进度、取消和显式续跑意图", async ({ page }) => {
  const browserErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(request.url()));
  await setAdminSession(page);
  await installApiMocks(page, "task-detail");
  let canceled = false;
  let resumeBody: Record<string, unknown> | undefined;
  await page.route("**/api/v1/ops/task-runs/1/cancel", async (route) => {
    canceled = true;
    await route.fulfill({ json: { id: 1, status: "canceled" } });
  });
  await page.route("**/api/v1/ops/task-runs/1/view", async (route) => {
    const view = createTaskRunView({ resource_key: "anns_d", title: "上市公司公告", status: canceled ? "canceled" : "running", unit_total: 3, unit_done: 1 });
    await route.fulfill({ json: { ...view, progress: { ...view.progress, announcement_progress: {
      phase: canceled ? "canceled" : "persisting", ann_date: "2026-01-01", page_number: 2, offset: 2000,
      unit_done: 1, unit_total: 3, issued_requests: 4, updated_at: "2026-10-02T00:00:00Z",
      counters: { observed: 2001, processed: 500, rejected: 0 }, quality_counts: { "quality.missing_rec_time": 3 },
    } } } });
  });
  await page.goto("/app/ops/tasks/1");
  await expect(page.getByText(/公告同步：保存/)).toBeVisible();
  await expect(page.getByText(/完成 1\/3 日/)).toBeVisible();
  await expect(page.getByText(/真实请求累计 4/)).toBeVisible();
  await page.getByRole("button", { name: "停止处理" }).click();
  await expect(page.getByText(/公告同步：已停止/)).toBeVisible();

  await page.route("**/api/v1/ops/manual-actions", async (route) => route.fulfill({ json: { groups: [{
    group_key: "news", group_label: "公告", group_order: 1, actions: [{
      action_key: "anns_d.maintain", action_type: "dataset_action", display_name: "维护上市公司公告",
      resource_key: "anns_d", resource_display_name: "上市公司公告", description: "按自然日维护公告", action_order: 1,
      date_model: { date_axis: "calendar_day", bucket_rule: "not_applicable", window_mode: "point_or_range", input_shape: "ann_date_or_start_end", observed_field: "ann_date", audit_applicable: false, not_applicable_reason: "公告不每日保证" },
      time_form: { default_mode: "point", modes: [{ mode: "point", label: "一天", description: "自然日", control: "calendar_date", selection_rule: "calendar_day", date_field: "ann_date" }] },
      filters: [], route_keys: ["anns_d.maintain"], search_keywords: ["公告"],
    }],
  }] } }));
  await page.route("**/api/v1/ops/manual-actions/anns_d.maintain/task-runs", async (route) => {
    resumeBody = route.request().postDataJSON();
    await route.fulfill({ json: createTaskRunView({ id: 901, resource_key: "anns_d", status: "queued" }) });
  });
  await page.goto("/app/ops/v21/datasets/tasks?tab=manual&action_key=anns_d.maintain&action_type=dataset_action&trade_date=2026-01-01");
  await expect(page.getByLabel("续跑来源任务 ID（可选）")).toBeVisible();
  await page.getByLabel("续跑来源任务 ID（可选）").fill("1");
  await page.getByRole("button", { name: "提交维护任务" }).click();
  await expect.poll(() => resumeBody?.resume_from_task_run_id).toBe(1);
  expect(resumeBody?.filters).toEqual({});
  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
