import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsV21SourcePage } from "./ops-v21-source-page";

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

  return render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <OpsV21SourcePage sourceKey="tushare" title="数据集 · Tushare" />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("V2.1 数据源详情页", () => {
  it("移除旧 glass 卡面并使用统一状态标签展示原始下载状态", async () => {
    apiRequest.mockImplementation(async (url: string) => {
      if (url === "/api/v1/ops/pipeline-modes?limit=2000") {
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
              raw_table: "raw_tushare.daily",
              std_table_hint: null,
              serving_table: "core_serving.daily",
              freshness_status: "fresh",
              latest_business_date: "2026-04-17",
              std_mapping_configured: true,
              std_cleansing_configured: true,
              resolution_policy_configured: true,
            },
          ],
        };
      }
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
      if (url === "/api/v1/ops/layer-snapshots/latest?source_key=tushare&stage=raw&limit=1000") {
        return {
          total: 1,
          items: [
            {
              snapshot_date: "2026-04-17",
              dataset_key: "daily",
              source_key: "tushare",
              stage: "raw",
              status: "success",
              rows_in: 100,
              rows_out: 100,
              error_count: 0,
              lag_seconds: 0,
              message: null,
              calculated_at: "2026-04-17T09:10:00+08:00",
              last_success_at: "2026-04-17T09:10:00+08:00",
              last_failure_at: null,
            },
          ],
        };
      }
      if (url === "/api/v1/ops/probes?source_key=tushare&limit=200") {
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
      throw new Error(`unexpected url: ${url}`);
    });

    renderPage();

    expect(await screen.findByText("数据集 · Tushare")).toBeInTheDocument();
    expect(await screen.findByText("股票日线")).toBeInTheDocument();
    expect(await screen.findByText("raw_tushare.daily")).toBeInTheDocument();
    expect(await screen.findByText("正常")).toBeInTheDocument();
    expect(await screen.findByText("自动探测")).toBeInTheDocument();
    const datasetCard = screen.getByText("股票日线").closest("[data-with-border='true']");
    expect(datasetCard).not.toBeNull();
    expect(datasetCard?.className).not.toContain("glass-card");
  });
});
