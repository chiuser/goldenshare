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
          total_executions: 0,
          queued_executions: 0,
          running_executions: 0,
          success_executions: 0,
          failed_executions: 0,
          canceled_executions: 0,
          partial_success_executions: 0,
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
        recent_executions: [],
        recent_failures: [],
      };
    }
    if (url.startsWith("/api/v1/ops/pipeline-modes")) {
      return {
        total: 1,
        items: [
          {
            dataset_key: "daily",
            display_name: "股票日线",
            domain_key: "equity",
            domain_display_name: "股票",
            mode: "single_source_direct",
            source_scope: "tushare",
            layer_plan: "raw,serving",
            raw_table: "raw_tushare.equity_daily_bar",
            std_table_hint: null,
            serving_table: "core_serving.equity_daily_bar",
            freshness_status: "fresh",
            latest_business_date: "2026-04-16",
            std_mapping_configured: true,
            std_cleansing_configured: true,
            resolution_policy_configured: true,
          },
        ],
      };
    }
    if (url.startsWith("/api/v1/ops/layer-snapshots/latest")) {
      return {
        total: 2,
        items: [
          {
            snapshot_date: "2026-04-17",
            dataset_key: "daily",
            source_key: "tushare",
            stage: "raw",
            status: "success",
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
            snapshot_date: "2026-04-17",
            dataset_key: "daily",
            source_key: null,
            stage: "serving",
            status: "success",
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
