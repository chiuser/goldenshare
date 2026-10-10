import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { OpsWeeklyAdjProgress } from "./ops-weekly-adj-progress";
import { appTheme } from "../app/theme";

it("shows the backend stage, historical range, retained rows and unavailable ETA", () => {
  render(<MantineProvider theme={appTheme}><OpsWeeklyAdjProgress progress={{
    stage: "刷新股票历史", updated_at: "2026-10-10T00:00:00Z", ts_code: "000001.SZ",
    start_date: "20100101", end_date: "20261009", unit_done: 1, unit_total: 2,
    page_number: 1, rows_preserved: 3, eta: "unavailable",
  }} /></MantineProvider>);
  expect(screen.getByText("复权周线：刷新股票历史")).toBeVisible();
  expect(screen.getByText(/000001.SZ｜20100101 至 20261009/)).toBeVisible();
  expect(screen.getByText("完成 1/2 单元｜保留未刷新 3 条")).toBeVisible();
  expect(screen.getByText(/预计完成：暂无法估算/)).toBeVisible();
});
