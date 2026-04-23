import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsV21DatasetDetailPage } from "./ops-v21-dataset-detail-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
}));

vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    Link: ({ to, children, ...props }: { to: string; children?: unknown }) => (
      <a href={to} {...props}>
        {children as string | number | null | undefined}
      </a>
    ),
  };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <OpsV21DatasetDetailPage datasetKey="daily" />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("V2.1 数据集详情页", () => {
  it("使用统一指标面板和数据表展示详情状态与执行记录", async () => {
    apiRequest.mockImplementation(async (url: string) => {
      if (url === "/api/v1/ops/freshness") {
        return {
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
                  job_name: "sync_daily.daily",
                  display_name: "股票日线",
                  cadence: "daily",
                  target_table: "core_serving.daily",
                  raw_table: "raw_tushare.daily",
                  state_business_date: "2026-04-17",
                  earliest_business_date: "2026-04-01",
                  observed_business_date: "2026-04-17",
                  latest_business_date: "2026-04-17",
                  business_date_source: "latest_business_date",
                  freshness_note: null,
                  latest_success_at: "2026-04-17T09:10:00+08:00",
                  last_sync_date: "2026-04-17",
                  expected_business_date: "2026-04-17",
                  lag_days: 0,
                  freshness_status: "fresh",
                  recent_failure_message: null,
                  recent_failure_summary: null,
                  recent_failure_at: null,
                  primary_execution_spec_key: "sync_daily.daily",
                  auto_schedule_status: "active",
                  auto_schedule_total: 1,
                  auto_schedule_active: 1,
                  auto_schedule_next_run_at: "2026-04-18T16:00:00+08:00",
                  active_execution_status: null,
                  active_execution_started_at: null,
                },
              ],
            },
          ],
        };
      }
      if (url === "/api/v1/ops/layer-snapshots/latest?dataset_key=daily&limit=200") {
        return {
          total: 3,
          items: [
            {
              snapshot_date: "2026-04-17",
              dataset_key: "daily",
              source_key: "tushare",
              stage: "raw",
              status: "success",
              rows_in: 120,
              rows_out: 120,
              error_count: 0,
              lag_seconds: 0,
              message: null,
              calculated_at: "2026-04-17T09:10:00+08:00",
              last_success_at: "2026-04-17T09:10:00+08:00",
              last_failure_at: null,
            },
            {
              snapshot_date: "2026-04-17",
              dataset_key: "daily",
              source_key: "tushare",
              stage: "serving",
              status: "success",
              rows_in: 120,
              rows_out: 120,
              error_count: 0,
              lag_seconds: 1800,
              message: null,
              calculated_at: "2026-04-17T09:30:00+08:00",
              last_success_at: "2026-04-17T09:30:00+08:00",
              last_failure_at: null,
            },
            {
              snapshot_date: "2026-04-17",
              dataset_key: "daily",
              source_key: "tushare",
              stage: "std",
              status: "warning",
              rows_in: 120,
              rows_out: 118,
              error_count: 1,
              lag_seconds: 1200,
              message: "部分记录待复核",
              calculated_at: "2026-04-17T09:20:00+08:00",
              last_success_at: "2026-04-17T09:20:00+08:00",
              last_failure_at: null,
            },
          ],
        };
      }
      if (url === "/api/v1/ops/layer-snapshots/history?dataset_key=daily&limit=50") {
        return {
          total: 12,
          items: [],
        };
      }
      if (url === "/api/v1/ops/executions?dataset_key=daily&limit=20") {
        return {
          total: 1,
          items: [
            {
              id: 101,
              spec_key: "sync_daily.daily",
              spec_display_name: "股票日线同步",
              trigger_source: "manual",
              status: "success",
              requested_at: "2026-04-17T09:00:00+08:00",
              started_at: "2026-04-17T09:00:02+08:00",
              ended_at: "2026-04-17T09:03:00+08:00",
              rows_fetched: 120,
              rows_written: 120,
              progress_current: 120,
              progress_total: 120,
              progress_percent: 100,
              progress_message: "done",
              last_progress_at: "2026-04-17T09:02:58+08:00",
              summary_message: "完成",
              error_code: null,
            },
          ],
        };
      }
      if (url === "/api/v1/ops/probes?dataset_key=daily&limit=20") {
        return {
          total: 1,
          items: [
            {
              id: 1,
              name: "股票日线探测",
              dataset_key: "daily",
              source_key: "tushare",
              status: "active",
              probe_interval_seconds: 600,
              window_start: "15:00",
              window_end: "18:00",
              last_probed_at: "2026-04-17T15:30:00+08:00",
              last_triggered_at: null,
              updated_at: "2026-04-17T15:31:00+08:00",
            },
          ],
        };
      }
      if (url === "/api/v1/ops/releases?dataset_key=daily&limit=20") {
        return {
          total: 1,
          items: [
            {
              id: 8,
              dataset_key: "daily",
              target_policy_version: 3,
              status: "completed",
              triggered_by_username: "admin",
              triggered_at: "2026-04-17T10:00:00+08:00",
              finished_at: "2026-04-17T10:01:00+08:00",
              updated_at: "2026-04-17T10:01:00+08:00",
            },
          ],
        };
      }
      if (url === "/api/v1/ops/std-rules/mapping?dataset_key=daily&limit=100") {
        return {
          total: 3,
          items: [],
        };
      }
      if (url === "/api/v1/ops/std-rules/cleansing?dataset_key=daily&limit=100") {
        return {
          total: 2,
          items: [],
        };
      }
      throw new Error(`unexpected url: ${url}`);
    });

    renderPage();

    expect(await screen.findByText("daily · 股票日线")).toBeInTheDocument();
    expect(await screen.findByText("全链路层级状态")).toBeInTheDocument();
    expect(await screen.findByText("数据来源状态")).toBeInTheDocument();
    expect(await screen.findByText("近期执行记录")).toBeInTheDocument();
    expect(await screen.findByText("策略 v3")).toBeInTheDocument();
    expect(await screen.findByText("101")).toBeInTheDocument();
    expect(await screen.findByText("tushare")).toBeInTheDocument();
  });
});
