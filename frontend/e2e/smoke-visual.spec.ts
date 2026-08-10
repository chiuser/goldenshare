import { expect, test } from "@playwright/test";

import { installApiMocks, setAdminSession, stabilizeUi } from "./support/smoke-fixtures";

test.describe("Phase 2 smoke and visual gate", () => {
  test("login page keeps the auth layout baseline", async ({ page }) => {
    await page.goto("/app/login");
    await expect(page.getByRole("heading", { name: "登录前端应用" })).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("ops overview keeps the shell and dataset card baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "ops-overview");
    await page.goto("/app/ops/v21/overview");
    await expect(page.getByText("状态概览")).toBeVisible();
    await expect(page.getByText("股票日线")).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("task center records keeps the core task table baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-records");
    await page.goto("/app/ops/v21/datasets/tasks?tab=records");
    await expect(page.getByRole("tab", { name: "任务记录" })).toBeVisible();
    await expect(page.getByText("当前筛选任务")).toBeVisible();
    await expect(
      page.getByRole("table").getByRole("link", { name: "查看详情" }).first(),
    ).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("task center default entry keeps the records default and tab switching baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-center");
    await page.goto("/app/ops/v21/datasets/tasks");
    await expect(page.getByRole("tab", { name: "任务记录", selected: true })).toBeVisible();
    await expect(page.getByRole("table").getByRole("link", { name: "查看详情" }).first()).toBeVisible();
    await page.getByRole("tab", { name: "自动运行" }).click();
    await expect(page).toHaveURL(/tab=auto/);
    await expect(page.getByRole("tab", { name: "自动运行", selected: true })).toBeVisible();
    await expect(page.getByText("任务详情", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "修改" })).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("task center manual keeps the guided maintenance baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-manual");
    await page.goto("/app/ops/v21/datasets/tasks?tab=manual");
    await expect(page.getByText("发起一次手动维护")).toBeVisible();
    await expect(page.getByText("第一步：选择要维护的数据")).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("task center manual keeps the trade date and submit baseline", async ({ page }) => {
    await setAdminSession(page);
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "goldenshare.frontend.ops.task-center.manual.domain",
        JSON.stringify("股票行情"),
      );
      window.localStorage.setItem(
        "goldenshare.frontend.ops.task-center.manual.draft",
        JSON.stringify({
          action_id: "daily",
          date_mode: "single_point",
          selected_date: "2026-04-17",
          start_date: "2026-04-17",
          end_date: "2026-04-17",
          selected_month: "",
          start_month: "",
          end_month: "",
          field_values: {},
        }),
      );
    });
    await installApiMocks(page, "task-manual");
    await page.goto("/app/ops/v21/datasets/tasks?tab=manual&action_key=daily.maintain&action_type=dataset_action&trade_date=2026-04-17");
    await expect(page.getByText("维护股票日线", { exact: true }).first()).toBeVisible();
    await expect(page.getByLabel("选择日期")).toBeVisible();
    await page.getByRole("button", { name: "选择日期" }).click();
    await page.getByRole("button", { name: "17" }).click();
    await expect(page.getByText("2026-04-17")).toBeVisible();
    await expect(page.getByRole("button", { name: "提交维护任务" })).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
    await page.getByRole("button", { name: "提交维护任务" }).click();
    await expect(page).toHaveURL("/app/ops/tasks/901");
    await expect(page.getByText("任务等待处理", { exact: true })).toBeVisible();
    await expect(page.getByText("当前进度", { exact: true })).toBeVisible();
  });

  test("task center auto keeps the schedule list and detail baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-auto");
    await page.goto("/app/ops/automation");
    await expect(page.getByRole("button", { name: "新建自动任务" })).toBeVisible();
    await expect(page.getByText("任务详情", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "修改" }).click();
    await expect(page.getByText("修改自动任务")).toBeVisible();
    await expect(page.getByText("预览未来 5 次运行时间（自动更新）")).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("task center auto locks the margin-detail source readiness contract", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-auto");
    await page.goto("/app/ops/automation");
    await page.getByRole("button", { name: "新建自动任务" }).click();

    await page.getByRole("textbox", { name: "先选数据分组" }).click();
    await page.getByRole("option", { name: "融资融券", exact: true }).click();
    await page.getByRole("textbox", { name: "再选执行对象" }).click();
    await page.getByRole("option", { name: "【数据】融资融券交易明细", exact: true }).click();

    await expect(page.getByRole("textbox", { name: "触发方式" })).toHaveValue("探测触发");
    await expect(page.getByRole("textbox", { name: "探测条件" })).toHaveValue("源站已完整发布融资融券交易明细");
    await expect(page.getByText("确认三个市场代表证券均已返回上一开市日数据后，创建全市场单日维护任务。")).toBeVisible();
    await expect(page.getByLabel("探测窗口开始")).toHaveValue("09:00");
    await expect(page.getByLabel("探测窗口结束")).toHaveValue("09:30");
    await expect(page.getByLabel("探测频率（秒）")).toHaveValue("300");
    await expect(page.getByLabel("每日触发上限")).toHaveValue("1");
    await expect(page.getByLabel("探测窗口开始")).toBeDisabled();
    await expect(page.getByLabel("探测窗口结束")).toBeDisabled();
    await expect(page.getByLabel("探测频率（秒）")).toBeDisabled();
    await expect(page.getByLabel("每日触发上限")).toBeDisabled();
    await expect(page.getByText("可选：固定维护日期")).not.toBeVisible();
    await expect(page.getByText("可选：附加筛选条件")).not.toBeVisible();
  });

  test("task detail keeps the progress and execution node baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-detail");
    await page.goto("/app/ops/tasks/1");
    await expect(page.getByText("执行过程", { exact: true })).toBeVisible();
    await expect(page.getByText("股票日线", { exact: true })).toBeVisible();
    await expect(page.getByText("当前进度", { exact: true })).toBeVisible();
    await expect(page.getByText("处理范围", { exact: true })).toBeVisible();
    await expect(page.getByText("2026-03-23 ~ 2026-03-30", { exact: true })).toBeVisible();
    await expect(page.getByText("建议下一步", { exact: true })).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("task detail shows paged quarter progress across polling snapshots", async ({ page }) => {
    const consoleErrors: string[] = [];
    const phases: string[] = [];
    let viewRequestCount = 0;
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(message.text());
      }
    });
    page.on("request", (request) => {
      if (request.url().includes("/api/v1/ops/task-runs/1/view")) {
        viewRequestCount += 1;
      }
    });
    page.on("response", async (response) => {
      if (!response.url().includes("/api/v1/ops/task-runs/1/view") || !response.ok()) {
        return;
      }
      const payload = await response.json();
      phases.push(payload.progress.paged_unit_progress.active?.phase ?? "completed");
    });

    await setAdminSession(page);
    await installApiMocks(page, "task-detail-paged");
    await page.setViewportSize({ width: 1024, height: 1200 });
    await page.goto("/app/ops/tasks/1");

    await expect(page.getByText("截至 2025-06-30｜正在处理第 1 页｜已完成 0 页｜累计读取 0 行")).toBeVisible();
    await expect(page.getByText("截至 2025-03-31｜季度处理完成")).toBeVisible();
    await expect(page.getByText("截至 2025-06-30｜正在处理第 2 页｜已完成 1 页｜累计读取 2,000 行")).toBeVisible({ timeout: 5000 });
    await stabilizeUi(page);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await expect(page).toHaveScreenshot();
    await expect(page.getByText("截至 2025-06-30｜源端拉取完成：共 2 页、3,270 行｜正在正式写入")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("截至 2025-06-30｜季度处理完成")).toBeVisible({ timeout: 5000 });

    await expect.poll(() => phases).toEqual(["processing_page", "processing_page", "publishing", "completed"]);
    expect(viewRequestCount).toBeGreaterThanOrEqual(4);
    expect(consoleErrors).toEqual([]);
  });

  test("review index keeps the review center list baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "review-index");
    await page.goto("/app/ops/v21/review/index");
    await expect(page.getByText("审查中心 · 指数")).toBeVisible();
    await expect(page.getByText("激活池管理")).toBeVisible();
    await expect(page.getByText("指数列表")).toBeVisible();
    await expect(page.getByText("沪深300")).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("review board keeps the review center board baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "review-board");
    await page.goto("/app/ops/v21/review/board?tab=equity");
    await expect(page.getByText("审查中心 · 板块")).toBeVisible();
    await expect(page.getByText("筛选条件")).toBeVisible();
    await expect(page.getByRole("tab", { name: "股票所属板块", selected: true })).toBeVisible();
    await expect(page.getByText("浦发银行")).toBeVisible();
    await expect(page.getByText("DC · 银行")).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

});
