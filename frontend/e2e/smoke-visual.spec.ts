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

  test("review index keeps the review center list baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "review-index");
    await page.goto("/app/ops/v21/review/index");
    await expect(page.getByText("审查中心 · 指数")).toBeVisible();
    await expect(page.getByText("筛选与资源池")).toBeVisible();
    await expect(page.getByText("激活指数列表")).toBeVisible();
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

  test("share market keeps the market snapshot baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "share-market");
    await page.goto("/app/share");
    await expect(page.getByText("市场总览")).toBeVisible();
    await expect(page.getByText("成交额前十")).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });
});
