import { expect, test } from "@playwright/test";

import { installApiMocks, setAdminSession } from "./support/smoke-fixtures";

test("index monthly schedule shows the trading-day rule and previews the chosen time", async ({ page }) => {
  await setAdminSession(page);
  await installApiMocks(page, "task-auto");
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.route("**/api/v1/ops/catalog", (route) => route.fulfill({
    json: {
      actions: [{
        key: "index_monthly.maintain",
        action_type: "dataset_action",
        display_name: "维护指数月线",
        target_key: "index_monthly",
        target_display_name: "指数月线",
        group_label: "指数",
        schedule_enabled: true,
        parameters: [
          { key: "trade_date", param_type: "date", display_name: "交易日期", required: false },
          { key: "ts_code", param_type: "string", display_name: "指数代码", required: false },
        ],
        automation_capability: {
          version: 1,
          default_trigger_mode: "schedule",
          trigger_options: [{ mode: "schedule", allowed_schedule_types: ["cron"] }],
          probe_conditions: [],
          calendar_policy_rules: [{
            policy: "monthly_first_trading_day",
            schedule_types: ["cron"],
            cron_repeat_modes: ["daily"],
            explicit_time_input: "forbidden",
            generated_time_mode: "point",
            generated_time_field: "trade_date",
            policy_parameters: [],
          }],
        },
      }],
      workflows: [],
    },
  }));
  await page.route("**/api/v1/ops/schedules/preview", (route) => route.fulfill({
    json: { preview_times: ["2026-05-06T19:10:00+08:00"] },
  }));
  await page.route("**/api/v1/ops/schedules", (route) => (
    route.request().method() === "POST" ? route.fulfill({
      json: {
        ...route.request().postDataJSON(),
        id: 201, status: "active", next_run_at: "2026-05-06T19:10:00+08:00",
      },
    }) : route.fallback()
  ));

  await page.goto("/app/ops/automation");
  await page.getByRole("button", { name: "新建自动任务" }).click();
  await page.getByRole("textbox", { name: "先选数据分组" }).click();
  await page.getByRole("option", { name: "指数", exact: true }).click();
  await page.getByRole("textbox", { name: "再选执行对象" }).click();
  await page.getByRole("option", { name: "【数据】指数月线", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "重复方式" })).toHaveValue("每月首个交易日");
  await expect(page.getByRole("textbox", { name: "时区", exact: true })).toBeDisabled();
  await expect(page.getByLabel("执行时间", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "维护参数" }).click();
  await expect(page.getByText("可选：固定维护日期")).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "指数代码" })).toHaveCount(0);

  const preview = page.waitForResponse((response) => (
    response.url().endsWith("/api/v1/ops/schedules/preview")
    && response.request().postDataJSON()?.calendar_policy === "monthly_first_trading_day"
  ));
  await page.getByLabel("执行时间", { exact: true }).fill("19:10");
  const response = await preview;
  expect(response.ok()).toBe(true);
  expect(response.request().postDataJSON()).toMatchObject({
    calendar_policy: "monthly_first_trading_day", schedule_type: "cron",
    cron_expr: "10 19 * * *", timezone: "Asia/Shanghai", next_run_at: null,
  });
  await expect(page.getByText("预览未来 5 次运行时间（自动更新）")).toBeVisible();
  await page.getByLabel("任务名称").fill("指数月线 Raw");
  const save = page.waitForResponse((result) => (
    result.url().endsWith("/api/v1/ops/schedules") && result.request().method() === "POST"
  ));
  await page.getByRole("button", { name: "创建自动任务" }).click();
  const saved = await save;
  expect(saved.ok()).toBe(true);
  expect(saved.request().postDataJSON()).toMatchObject({
    target_type: "dataset_action", target_key: "index_monthly.maintain",
    calendar_policy: "monthly_first_trading_day",
    params_json: { time_input: { mode: "point" }, filters: {} },
  });
  expect(saved.request().postDataJSON().params_json).not.toHaveProperty("time_input.trade_date");
  expect(saved.request().postDataJSON().params_json).not.toHaveProperty("filters.ts_code");
  await expect(page.getByText("自动任务已创建")).toBeVisible();
  expect(pageErrors).toEqual([]);
});
