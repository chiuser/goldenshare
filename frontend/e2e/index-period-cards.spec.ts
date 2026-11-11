import { expect, test } from "@playwright/test";
import { createTaskRunView, installApiMocks, setAdminSession } from "./support/smoke-fixtures";

// Full card contract from DatasetCardItem. Task detail uses the existing TaskRun view fixture.
function card(period: "weekly" | "monthly", serving: boolean) {
  const key = `index_${period}${serving ? "_serving" : ""}`;
  const day = serving ? "2026-11-10" : period === "weekly" ? "2026-11-06" : "2026-10-30";
  const action = serving ? `maintenance.update_index_${period}_serving` : `index_${period}.maintain`;
  return {
    card_key: key, dataset_key: key, detail_dataset_key: key, resource_key: key,
    display_name: `指数${period === "weekly" ? "周" : "月"}线${serving ? " Serving" : ""}`,
    group_key: "index_market_data", group_label: "A股指数行情", group_order: 50, item_order: period === "weekly" ? 10 : 20,
    domain_key: serving ? "biz_tableset" : "index_fund", domain_display_name: serving ? "Biz数据集" : "指数 / ETF",
    status: serving ? "failed" : "healthy", freshness_status: serving ? "failed" : "fresh",
    delivery_mode: serving ? "biz_table_snapshot" : "raw_collection", delivery_mode_label: serving ? "业务派生表" : "Raw采集",
    delivery_mode_tone: "info", layer_plan: serving ? "biz_tableset" : "raw-only", freshness_policy: serving ? "index_period_serving" : "period_bucket",
    raw_table: serving ? null : `raw_tushare.index_${period}_bar`, raw_table_label: serving ? null : `raw_tushare.index_${period}_bar`,
    target_table: serving ? `core_serving.index_${period}_serving` : `raw_tushare.index_${period}_bar`,
    latest_business_date: day, earliest_business_date: day, latest_observed_at: null, earliest_observed_at: null,
    last_sync_date: day, latest_success_at: null, expected_business_date: day, latest_observed_date: day,
    latest_observed_date_label: serving ? "数据截至日" : "最新业务日期", expected_observed_date: day,
    expected_observed_date_label: serving ? "日更目标交易日" : "应到正式期末", last_success_label: "最近维护成功时间",
    lag_days: 0, freshness_note: null, primary_action_type: serving ? "maintenance_action" : "dataset_action", primary_action_key: action,
    active_task_run_status: null, active_task_run_started_at: null, auto_schedule_status: "active", auto_schedule_total: 1,
    auto_schedule_active: 1, auto_schedule_next_run_at: "2026-11-11T22:00:00+08:00", probe_total: 0, probe_active: 0,
    std_mapping_configured: false, std_cleansing_configured: false, resolution_policy_configured: false,
    updated_code_count: serving ? 9 : null, expected_code_count: serving ? 10 : null,
    latest_task_run: serving ? {
      id: 42, task_type: "maintenance_action", resource_key: null, action_key: action, action: "maintain", title: "指数 Serving 更新",
      trigger_source: "manual", trigger_source_label: "手动", status: "failed", status_reason_code: "index_period_serving.code_failures",
      requested_by_username: "admin", requested_at: "2026-11-10T22:00:00+08:00", started_at: null, ended_at: null,
      time_scope: { kind: "point", start: day, end: day, label: day }, time_scope_label: day, schedule_display_name: null,
      unit_total: 10, unit_done: 10, unit_failed: 1, progress_percent: 100, rows_fetched: 10, rows_saved: 9, rows_rejected: 0,
      rows_deduplicated: 0, primary_issue_id: 91, primary_issue_title: "指数日线缺失",
    } : null,
  };
}

test.beforeEach(async ({ page }) => {
  await setAdminSession(page);
  await installApiMocks(page, "manual");
  await page.route("**/api/v1/ops/dataset-cards*", (route) => {
    const serving = new URL(route.request().url()).searchParams.get("source_key") === "biz_tableset";
    return route.fulfill({ json: { total: 2, groups: [{ group_key: "index_market_data", group_label: "A股指数行情", group_order: 50,
      items: [card("weekly", serving), card("monthly", serving)] }] } });
  });
  await page.route("**/api/v1/ops/manual-actions", (route) => route.fulfill({ json: { groups: [{
    group_key: "maintenance", group_label: "系统维护", group_order: 10,
    actions: ["weekly", "monthly"].map((frequency) => ({
      action_key: `maintenance.update_index_${frequency}_serving`, action_type: "maintenance_action",
      display_name: `更新指数${frequency === "weekly" ? "周" : "月"}线 Serving`, description: "指定交易日更新指数 Serving。",
      resource_key: null, resource_display_name: null, date_model: null,
      time_form: { default_mode: "point", modes: [{ mode: "point", label: "只处理一天", description: "指定目标交易日。",
        control: "trade_date", selection_rule: "trading_day_only", date_field: "trade_date" }], max_units_per_execution: null },
      conditional_time_rules: [], filters: [], search_keywords: [], action_order: 10,
    })),
  }] } }));
});

test("Serving cards show pool coverage and open the existing manual task", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => { if (response.url().includes("/api/") && response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
  await page.goto("/app/ops/v21/datasets/biz");
  await expect(page.getByText("已更新指数：9/10", { exact: true })).toHaveCount(2);
  await expect(page.getByText("日更目标交易日：2026/11/10", { exact: true })).toHaveCount(2);
  await expect(page.getByRole("link", { name: "任务 #42" })).toHaveCount(2);
  expect(await page.locator("body").evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("serving-cards.png"), fullPage: true });
  await page.getByRole("link", { name: "去操作" }).first().click();
  await expect(page).toHaveURL(/tab=manual&action_key=maintenance.update_index_weekly_serving/);
  await expect(page.getByText("指定交易日更新指数 Serving。", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("Raw cards show formal dates and Serving task detail exposes missing code", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => { if (response.url().includes("/api/") && response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
  await page.goto("/app/ops/v21/datasets/tushare");
  await expect(page.getByText("raw_tushare.index_weekly_bar", { exact: true })).toBeVisible();
  await expect(page.getByText("应到正式期末：2026/11/06", { exact: true })).toBeVisible();
  await expect(page.getByText("应到正式期末：2026/10/30", { exact: true })).toBeVisible();
  await expect(page.getByText("已更新指数", { exact: false })).toHaveCount(0);
  expect(await page.locator("body").evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("raw-cards.png"), fullPage: true });
  await page.route("**/api/v1/ops/task-runs/42/view", (route) => {
    const base = createTaskRunView({ id: 42, title: "指数周线 Serving 更新", status: "failed", rows_saved: 9,
      unit_total: 10, unit_done: 10, unit_failed: 1, time_input: { mode: "point", trade_date: "2026-11-10" } });
    return route.fulfill({ json: { ...base, run: { ...base.run, task_type: "maintenance_action", resource_key: null,
      action_key: "maintenance.update_index_weekly_serving", source_key: null },
      primary_issue: { id: 91, code: "index_period_serving.code_failures", severity: "error", title: "指数日线缺失",
        operator_message: "899050.BJ：2026-11-10 指数日线缺失", suggested_action: "补齐日线后按原日期重试。",
        source_phase: "execute", occurred_at: "2026-11-10T22:00:00+08:00", object: null } } });
  });
  await page.goto("/app/ops/v21/datasets/biz");
  await page.getByRole("link", { name: "任务 #42" }).first().click();
  await expect(page).toHaveURL(/\/ops\/tasks\/42$/);
  await expect(page.getByText("899050.BJ：2026-11-10 指数日线缺失", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
