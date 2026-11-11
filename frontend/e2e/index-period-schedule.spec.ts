import { expect, test } from "@playwright/test";

import { installApiMocks, setAdminSession } from "./support/smoke-fixtures";

// LLD §10 and the actual automation capability response checked by the backend API tests.
const servingAction = {
  key: "maintenance.update_index_weekly_serving", action_type: "maintenance_action",
  display_name: "更新指数周线 Serving", target_key: "index_weekly_serving",
  target_display_name: "指数周线 Serving", group_label: "维护动作", schedule_enabled: true,
  parameters: [
    { key: "trade_date", display_name: "处理日期", param_type: "date", required: false, description: "只处理一个交易日。" },
    { key: "ts_code", display_name: "指数代码", param_type: "string", required: false,
      description: "指定周、月线 Serving 激活池内的一个指数。留空处理全池。" },
  ],
  automation_capability: {
    version: 1, default_trigger_mode: "schedule",
    trigger_options: [{ mode: "schedule", allowed_schedule_types: ["cron"] }, { mode: "probe", allowed_schedule_types: ["cron"] }],
    probe_conditions: [{ kind: "index_period_serving_ready", label: "指数 Serving 所需数据齐备",
      description: "检查独立池内全部指数的 Prod Raw 和更新连续性。", allowed_trigger_modes: ["probe"],
      calendar_policy: "dataset_default", time_input: "forbidden", filters: { mode: "forbidden" },
      probe: { source: "system_default", source_label: "Prod Raw", window: { mode: "fixed", start: "19:00", end: "00:00" },
        probe_interval_seconds: { mode: "operator_default" }, max_triggers_per_day: { mode: "operator_default" } } }],
    calendar_policy_rules: [{ policy: "trading_day_point", schedule_types: ["cron"], cron_repeat_modes: ["daily"],
      explicit_time_input: "forbidden", generated_time_mode: "point", generated_time_field: "trade_date", policy_parameters: [] }],
  },
};

test("Serving probe form uses the backend window and saves a maintenance probe without cron", async ({ page }) => {
  await setAdminSession(page);
  await installApiMocks(page, "task-auto");
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("response", response => { if (response.url().includes("/api/") && response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
  await page.route("**/api/v1/ops/catalog", route => route.fulfill({ json: { actions: [servingAction], workflows: [] } }));
  await page.route("**/api/v1/ops/schedules", route => route.request().method() === "POST"
    ? route.fulfill({ json: { ...route.request().postDataJSON(), id: 201, status: "active", next_run_at: null } }) : route.fallback());
  await page.goto("/app/ops/automation");
  await page.getByRole("button", { name: "新建自动任务" }).click();
  await page.getByRole("textbox", { name: "先选数据分组" }).click();
  await page.getByRole("option", { name: "维护动作", exact: true }).click();
  await page.getByRole("textbox", { name: "再选执行对象" }).click();
  await page.getByRole("option", { name: "【维护】指数周线 Serving", exact: true }).click();
  await page.getByRole("textbox", { name: "触发方式" }).click();
  await page.getByRole("option", { name: "探测触发", exact: true }).click();
  await expect(page.getByLabel("探测窗口开始")).toHaveValue("19:00");
  await expect(page.getByLabel("探测窗口结束")).toHaveValue("00:00");
  await expect(page.getByLabel("探测频率（秒）")).toHaveValue("300");
  await expect(page.getByLabel("执行时间", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "维护参数" }).click();
  await expect(page.getByText("可选：固定维护日期")).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "指数代码" })).toHaveCount(0);
  await page.getByLabel("任务名称").fill("周线 Serving 探测");
  const saved = page.waitForResponse(response => response.url().endsWith("/api/v1/ops/schedules") && response.request().method() === "POST");
  await page.getByRole("button", { name: "创建自动任务" }).click();
  const response = await saved;
  expect(response.request().postDataJSON()).toMatchObject({ target_type: "maintenance_action",
    target_key: "maintenance.update_index_weekly_serving", trigger_mode: "probe", cron_expr: null, next_run_at: null,
    calendar_policy: "trading_day_point", probe_config: { condition_kind: "index_period_serving_ready",
      window_start: "19:00", window_end: "00:00", probe_interval_seconds: 300 } });
  await expect(page.getByText("自动任务已创建")).toBeVisible();
  expect(errors).toEqual([]);
});

for (const matched of [false, true]) {
  test(`Serving probe detail shows ${matched ? "the created task" : "the missing code and dates"}`, async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-auto");
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
    page.on("response", response => { if (response.url().includes("/api/") && response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
    const schedule = { id: 201, target_type: "maintenance_action", target_key: servingAction.key,
      target_display_name: "指数周线 Serving", display_name: "周线 Serving 探测", status: "active",
      schedule_type: "cron", trigger_mode: "probe", cron_expr: null, timezone: "Asia/Shanghai",
      calendar_policy: "trading_day_point", next_run_at: null, updated_at: "2026-11-10T19:05:00+08:00",
      probe_config: { source: "system_default", source_label: "Prod Raw", condition_kind: "index_period_serving_ready",
        window_start: "19:00", window_end: "00:00", probe_interval_seconds: 300, max_triggers_per_day: 1 },
      params_json: {}, retry_policy_json: {}, concurrency_policy_json: {} };
    await page.route("**/api/v1/ops/catalog", route => route.fulfill({ json: { actions: [servingAction], workflows: [] } }));
    await page.route("**/api/v1/ops/schedules", route => route.fulfill({ json: { total: 1, items: [schedule] } }));
    await page.route("**/api/v1/ops/schedules/201", route => route.fulfill({ json: schedule }));
    await page.route("**/api/v1/ops/probes?**", route => route.fulfill({ json: { total: 1, items: [{ id: 90,
      name: "指数周线 Serving", dataset_key: "index_weekly_serving", dataset_display_name: "指数周线 Serving",
      source_key: null, source_display_name: "Prod Raw", status: "active", probe_interval_seconds: 300,
      window_start: "19:00", window_end: "00:00", last_probed_at: "2026-11-10T19:05:00+08:00" }] } }));
    await page.route("**/api/v1/ops/probes/runs**", route => route.fulfill({ json: { total: 1, items: [{ id: 91,
      condition_matched: matched, message: matched ? "池内指数均具备 Serving 更新条件" : "Serving 所需数据尚未齐备：899050.BJ",
      probed_at: "2026-11-10T19:05:00+08:00", triggered_task_run_id: matched ? 902 : null,
      payload_json: { failures: matched ? [] : [{ ts_code: "899050.BJ", message: "指数 Raw 日线缺少应有交易日。", missing_dates: ["2026-11-10"] }] } }] } }));
    await page.goto("/app/ops/automation");
    await page.getByText("周线 Serving 探测", { exact: true }).click();
    await expect(page.getByText("Prod Raw", { exact: true })).toBeVisible();
    if (matched) {
      await expect(page.getByRole("link", { name: "查看 Serving 更新任务" })).toHaveAttribute("href", "/app/ops/tasks/902");
    } else {
      await expect(page.getByText(/缺失日期：2026-11-10/)).toBeVisible();
      await expect(page.getByRole("link", { name: "查看 Serving 更新任务" })).toHaveCount(0);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

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
