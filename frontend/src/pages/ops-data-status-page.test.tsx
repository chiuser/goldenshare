import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { formatDateLabel } from "../shared/date-format";
import { OpsDataStatusPage } from "./ops-data-status-page";

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async () => ({
    summary: {
      total_datasets: 1,
      fresh_datasets: 1,
      lagging_datasets: 0,
      stale_datasets: 0,
      unknown_datasets: 0,
    },
    groups: [
      {
        domain_key: "equity",
        domain_display_name: "股票",
        items: [
          {
            dataset_key: "daily",
            resource_key: "daily",
            job_name: "sync_equity_daily",
            display_name: "股票日线",
            cadence: "daily",
            target_table: "core.equity_daily_bar",
            state_business_date: "2026-03-30",
            earliest_business_date: "2020-01-01",
            observed_business_date: "2026-03-30",
            latest_business_date: "2026-03-30",
            business_date_source: "state+observed",
            freshness_note: "最新业务日同时被状态表和真实目标表观测到。",
            expected_business_date: "2026-03-30",
            lag_days: 0,
            freshness_status: "fresh",
            recent_failure_message: null,
            recent_failure_summary: null,
            recent_failure_at: null,
            primary_execution_spec_key: "sync_daily.daily",
          },
        ],
      },
    ],
  })),
}));

describe("数据状态页", () => {
  it("列表使用统一表格样式，并以按钮方式提供操作", async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <MantineProvider theme={appTheme}>
        <QueryClientProvider client={queryClient}>
          <OpsDataStatusPage />
        </QueryClientProvider>
      </MantineProvider>,
    );

    expect(await screen.findByText("数据状态")).toBeInTheDocument();
    expect(await screen.findByText("日期范围")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "查看任务" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "去处理" })).toBeInTheDocument();
    expect(await screen.findByText(`${formatDateLabel("2020-01-01")} ~ ${formatDateLabel("2026-03-30")}`)).toBeInTheDocument();
  });
});
