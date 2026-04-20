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
    await expect(
      page.getByRole("table").getByRole("link", { name: "查看详情" }).first(),
    ).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("task center manual keeps the guided maintenance baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-manual");
    await page.goto("/app/ops/manual-sync");
    await expect(page.getByText("这里只做一件事：维护你选中的数据。")).toBeVisible();
    await expect(page.getByText("第一步：选择要维护的数据")).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("task center auto keeps the schedule list and detail baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-auto");
    await page.goto("/app/ops/automation");
    await expect(page.getByRole("button", { name: "新建自动任务" })).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("task detail keeps the progress and event stream baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "task-detail");
    await page.goto("/app/ops/tasks/1");
    await expect(page.getByText("实时处理记录", { exact: true })).toBeVisible();
    await expect(page.getByText("股票日线维护")).toBeVisible();
    await stabilizeUi(page);
    await expect(page).toHaveScreenshot();
  });

  test("review index keeps the review center list baseline", async ({ page }) => {
    await setAdminSession(page);
    await installApiMocks(page, "review-index");
    await page.goto("/app/ops/v21/review/index");
    await expect(page.getByText("激活指数列表")).toBeVisible();
    await expect(page.getByText("沪深300")).toBeVisible();
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
