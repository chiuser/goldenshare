import { expect, test } from "@playwright/test";

import { installApiMocks, setAdminSession } from "./support/smoke-fixtures";

test("announcement daily configuration sends intent without browser-generated dates", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) {
      errors.push(`${response.status()} ${response.url()}`);
    }
  });
  await setAdminSession(page);
  await installApiMocks(page, "task-auto");
  await page.route("**/api/v1/ops/catalog", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ actions: [{
      key: "anns_d.maintain", action_type: "dataset_action", display_name: "维护上市公司公告",
      group_label: "新闻资讯", target_key: "anns_d", target_display_name: "上市公司公告",
      target_tables: ["raw_tushare.anns_d"], manual_enabled: true, schedule_enabled: true,
      retry_enabled: true, schedule_binding_count: 0, active_schedule_count: 0,
      parameters: ["trade_date", "start_date", "end_date"].map((key) => ({
        key, display_name: key, param_type: "date", required: false, multi_value: false, options: [],
      })),
      automation_capability: {
        version: 1, default_trigger_mode: "schedule", repeat_policy: null,
        time_input_contract: {
          supported_modes: ["point", "range"], point_field: "trade_date",
          range_start_field: "start_date", range_end_field: "end_date", granularity: "day",
        },
        trigger_options: [{ mode: "schedule", allowed_schedule_types: ["once", "cron"] }],
        probe_conditions: [], calendar_policy_rules: [{
          policy: "trigger_day_forward_range", schedule_types: ["cron"], cron_repeat_modes: ["daily"],
          explicit_time_input: "forbidden", generated_time_mode: "range", generated_time_field: "start_date_end_date",
        }],
      },
    }], workflows: [] }),
  }));
  await page.route("**/api/v1/ops/schedules", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({
      ...route.request().postDataJSON(), id: 202, target_display_name: "上市公司公告", status: "active",
      created_at: "2026-10-12T08:00:00+08:00", updated_at: "2026-10-12T08:00:00+08:00",
    }) });
  });
  await page.goto("/app/ops/automation");
  await page.getByRole("button", { name: "新建自动任务" }).click();
  await page.getByRole("textbox", { name: "先选数据分组" }).click();
  await page.getByRole("option", { name: "新闻资讯", exact: true }).click();
  await page.getByRole("textbox", { name: "再选执行对象" }).click();
  await page.getByRole("option", { name: "【数据】上市公司公告", exact: true }).click();
  await page.getByRole("button", { name: "维护参数", exact: true }).click();
  await expect(page.getByText("可选：固定维护日期", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "执行方式", exact: true }).click();
  await page.getByRole("option", { name: "按周期执行", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "重复方式" })).toHaveValue("每天");
  await expect(page.getByText("可选：固定维护日期", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/每天.*维护触发当天至次日/)).toBeVisible();
  const submitted = page.waitForRequest((request) => request.method() === "POST"
    && new URL(request.url()).pathname === "/api/v1/ops/schedules");
  await page.getByRole("button", { name: "创建自动任务", exact: true }).click();
  const body = (await submitted).postDataJSON();
  expect(body.calendar_policy).toBe("trigger_day_forward_range");
  expect(body.params_json).toEqual({
    dataset_key: "anns_d", action: "maintain", time_input: { mode: "range" }, filters: {},
  });
  expect(errors).toEqual([]);
});
