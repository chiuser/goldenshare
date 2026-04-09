import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { formatDateLabel } from "../shared/date-format";
import { OpsDataStatusPage } from "./ops-data-status-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
}));

function renderPage() {
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
}

describe("数据状态页", () => {
  it("列表使用统一表格样式，并只保留去处理按钮", async () => {
    apiRequest.mockResolvedValueOnce({
      summary: {
        total_datasets: 1,
        fresh_datasets: 1,
        lagging_datasets: 0,
        stale_datasets: 0,
        unknown_datasets: 0,
        disabled_datasets: 0,
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
              last_sync_date: "2026-03-30",
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
    });

    renderPage();

    expect(await screen.findByText("有业务日期的数据会显示覆盖范围；没有业务日期的数据会显示最近一次同步日期。")).toBeInTheDocument();
    expect(await screen.findByText("日期范围")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "去处理" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "查看任务" })).not.toBeInTheDocument();
    expect(await screen.findByText(`${formatDateLabel("2020-01-01")} ~ ${formatDateLabel("2026-03-30")}`)).toBeInTheDocument();
  });

  it("没有业务日期时显示最近同步日期", async () => {
    apiRequest.mockResolvedValueOnce({
      summary: {
        total_datasets: 1,
        fresh_datasets: 1,
        lagging_datasets: 0,
        stale_datasets: 0,
        unknown_datasets: 0,
        disabled_datasets: 0,
      },
      groups: [
        {
          domain_key: "board",
          domain_display_name: "板块",
          items: [
            {
              dataset_key: "ths_index",
              resource_key: "ths_index",
              job_name: "sync_ths_index",
              display_name: "同花顺概念和行业指数",
              cadence: "reference",
              target_table: "core.ths_index",
              state_business_date: null,
              earliest_business_date: null,
              observed_business_date: null,
              latest_business_date: null,
              business_date_source: "none",
              freshness_note: null,
              last_sync_date: "2026-04-01",
              expected_business_date: "2026-04-01",
              lag_days: 0,
              freshness_status: "fresh",
              recent_failure_message: null,
              recent_failure_summary: null,
              recent_failure_at: null,
              primary_execution_spec_key: "sync_history.ths_index",
            },
          ],
        },
      ],
    });

    renderPage();

    expect(await screen.findByText(formatDateLabel("2026-04-01"))).toBeInTheDocument();
    expect(screen.getByText("同花顺概念和行业指数")).toBeInTheDocument();
  });
});
