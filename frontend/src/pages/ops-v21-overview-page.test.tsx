import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsV21OverviewPage } from "./ops-v21-overview-page";

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
        <OpsV21OverviewPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

function mockOverviewDeps(overviewMode: "ok" | "error" = "ok") {
  apiRequest.mockImplementation(async (url: string) => {
    if (url === "/api/v1/ops/overview") {
      if (overviewMode === "error") {
        throw new Error("overview failed");
      }
      return {
        today_kpis: {
          business_date: "2026-04-17",
          total_requests: 0,
          completed_requests: 0,
          running_requests: 0,
          failed_requests: 0,
          queued_requests: 0,
          attention_dataset_count: 0,
        },
        kpis: {
          total_task_runs: 0,
          queued_task_runs: 0,
          running_task_runs: 0,
          success_task_runs: 0,
          failed_task_runs: 0,
          canceled_task_runs: 0,
          partial_success_task_runs: 0,
        },
        freshness_summary: {
          total_datasets: 12,
          fresh_datasets: 9,
          lagging_datasets: 2,
          stale_datasets: 1,
          unknown_datasets: 0,
          disabled_datasets: 0,
        },
        lagging_datasets: [],
        recent_task_runs: [],
        recent_failures: [],
      };
    }
    if (url === "/api/v1/ops/dataset-cards") {
      return {
        total: 1,
        groups: [
          {
            group_key: "equity_market",
            group_label: "A股行情",
            group_order: 2,
            items: [
              {
                card_key: "daily",
                dataset_key: "daily",
                detail_dataset_key: "daily",
                resource_key: "daily",
                display_name: "股票日线",
                group_key: "equity_market",
                group_label: "A股行情",
                group_order: 2,
                item_order: 80,
                domain_key: "equity",
                domain_display_name: "股票",
                status: "healthy",
                freshness_status: "fresh",
                delivery_mode: "single_source_serving",
                delivery_mode_label: "单源服务",
                delivery_mode_tone: "success",
                layer_plan: "raw->serving",
                cadence: "daily",
                cadence_display_name: "每日",
                raw_table: "raw_tushare.equity_daily_bar",
                raw_table_label: "raw_tushare.equity_daily_bar",
                target_table: "core_serving.equity_daily_bar",
                latest_business_date: "2026-04-16",
                earliest_business_date: "2026-04-01",
                last_sync_date: "2026-04-16",
                latest_success_at: "2026-04-17T01:01:00Z",
                expected_business_date: "2026-04-16",
                lag_days: 0,
                freshness_note: null,
                primary_action_key: "daily.maintain",
                active_task_run_status: null,
                active_task_run_started_at: null,
                auto_schedule_status: "none",
                auto_schedule_total: 0,
                auto_schedule_active: 0,
                auto_schedule_next_run_at: null,
                probe_total: 0,
                probe_active: 0,
                std_mapping_configured: true,
                std_cleansing_configured: true,
                resolution_policy_configured: true,
                status_updated_at: "2026-04-17T01:01:00Z",
                stage_statuses: [
                  {
                    stage: "raw",
                    stage_label: "原始层",
                    table_name: "raw_tushare.equity_daily_bar",
                    source_key: "tushare",
                    source_display_name: "Tushare",
                    status: "healthy",
                    rows_in: 1,
                    rows_out: 1,
                    error_count: 0,
                    lag_seconds: 0,
                    message: null,
                    calculated_at: "2026-04-17T01:00:00Z",
                    last_success_at: "2026-04-17T01:00:00Z",
                    last_failure_at: null,
                  },
                  {
                    stage: "serving",
                    stage_label: "服务层",
                    table_name: "core_serving.equity_daily_bar",
                    source_key: null,
                    source_display_name: null,
                    status: "healthy",
                    rows_in: 1,
                    rows_out: 1,
                    error_count: 0,
                    lag_seconds: 0,
                    message: null,
                    calculated_at: "2026-04-17T01:01:00Z",
                    last_success_at: "2026-04-17T01:01:00Z",
                    last_failure_at: null,
                  },
                ],
                raw_sources: [
                  {
                    source_key: "tushare",
                    source_display_name: "Tushare",
                    table_name: "raw_tushare.equity_daily_bar",
                    status: "healthy",
                    calculated_at: "2026-04-17T01:00:00Z",
                  },
                  {
                    source_key: "biying",
                    source_display_name: "Biying",
                    table_name: "raw_biying.equity_daily_bar",
                    status: "healthy",
                    calculated_at: "2026-04-17T01:00:00Z",
                  },
                ],
              },
            ],
          },
        ],
      };
    }
    throw new Error(`unexpected url: ${url}`);
  });
}

describe("V2.1 数据状态总览页", () => {
  it("在数据集卡片上方展示状态概览统计", async () => {
    mockOverviewDeps("ok");
    renderPage();

    expect(await screen.findByText("状态概览")).toBeInTheDocument();
    expect(await screen.findByText("数据集总数")).toBeInTheDocument();
    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(await screen.findByText("状态正常")).toBeInTheDocument();
    expect(await screen.findByText("9")).toBeInTheDocument();
    expect(await screen.findByText("股票日线")).toBeInTheDocument();
    const datasetCard = screen.getByTestId("overview-dataset-card-daily");
    expect(datasetCard.className).not.toContain("glass-card");
    expect(within(datasetCard).getByText("股票 · 单源服务")).toBeInTheDocument();
    expect(within(datasetCard).queryByText("daily")).not.toBeInTheDocument();
    expect(within(datasetCard).getByText("Tushare（raw_tushare.equity_daily_bar）")).toBeInTheDocument();
    expect(within(datasetCard).getByText("Biying（raw_biying.equity_daily_bar）")).toBeInTheDocument();
    expect(within(datasetCard).queryByText("tushare")).not.toBeInTheDocument();
    expect(within(datasetCard).queryByText("biying")).not.toBeInTheDocument();
    expect(within(datasetCard).getByText("映射规则")).toBeInTheDocument();
    expect(within(datasetCard).getAllByText("已配置").length).toBeGreaterThan(0);
  });

  it("状态概览读取失败时不影响下方数据集卡片展示", async () => {
    mockOverviewDeps("error");
    renderPage();

    expect(await screen.findByText("读取状态概览失败")).toBeInTheDocument();
    expect(await screen.findByText("股票日线")).toBeInTheDocument();
    expect(screen.queryByText("读取数据状态总览失败")).not.toBeInTheDocument();
  });
});
