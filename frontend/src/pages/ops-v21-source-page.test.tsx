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

function card(overrides: Partial<Record<string, unknown>>) {
  return {
    card_key: "daily",
    dataset_key: "daily",
    detail_dataset_key: "daily",
    resource_key: "daily",
    display_name: "股票日线",
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
    raw_table: "raw_tushare.daily",
    raw_table_label: "raw_tushare.daily",
    target_table: "core_serving.daily",
    latest_business_date: "2026-04-17",
    earliest_business_date: "2026-04-01",
    last_sync_date: "2026-04-17",
    latest_success_at: "2026-04-17T09:10:00+08:00",
    expected_business_date: "2026-04-17",
    lag_days: 0,
    freshness_note: null,
    primary_action_key: "daily.maintain",
    active_execution_status: null,
    active_execution_started_at: null,
    auto_schedule_status: "active",
    auto_schedule_total: 1,
    auto_schedule_active: 1,
    auto_schedule_next_run_at: "2026-04-18T16:00:00+08:00",
    probe_total: 1,
    probe_active: 1,
    std_mapping_configured: true,
    std_cleansing_configured: true,
    resolution_policy_configured: true,
    status_updated_at: "2026-04-17T09:10:00+08:00",
    stage_statuses: [],
    raw_sources: [],
    ...overrides,
  };
}

describe("V2.1 数据源详情页", () => {
  it("消费 dataset card view 展示原始下载状态", async () => {
    apiRequest.mockImplementation(async (url: string) => {
      if (url === "/api/v1/ops/dataset-cards?source_key=tushare") {
        return {
          total: 3,
          groups: [
            {
              domain_key: "equity",
              domain_display_name: "股票",
              items: [
                card({}),
                card({
                  card_key: "stk_factor_pro",
                  dataset_key: "stk_factor_pro",
                  detail_dataset_key: "stk_factor_pro",
                  resource_key: "stk_factor_pro",
                  display_name: "股票技术面因子(专业版)",
                  status: "warning",
                  freshness_status: "lagging",
                  raw_table: "raw_tushare.stk_factor_pro",
                  raw_table_label: "raw_tushare.stk_factor_pro",
                  latest_business_date: "2026-04-16",
                  last_sync_date: "2026-04-16",
                  latest_success_at: "2026-04-16T09:10:00+08:00",
                  expected_business_date: "2026-04-17",
                  lag_days: 1,
                  primary_action_key: "stk_factor_pro.maintain",
                  auto_schedule_status: "none",
                  auto_schedule_total: 0,
                  auto_schedule_active: 0,
                  auto_schedule_next_run_at: null,
                  probe_total: 0,
                  probe_active: 0,
                }),
              ],
            },
            {
              domain_key: "market",
              domain_display_name: "行情",
              items: [
                card({
                  card_key: "limit_list_ths",
                  dataset_key: "limit_list_ths",
                  detail_dataset_key: "limit_list_ths",
                  resource_key: "limit_list_ths",
                  display_name: "涨跌停列表（同花顺）",
                  domain_key: "market",
                  domain_display_name: "行情",
                  raw_table: "raw_tushare.limit_list_ths",
                  raw_table_label: "raw_tushare.limit_list_ths",
                  latest_business_date: "2026-04-24",
                  earliest_business_date: "2026-04-24",
                  last_sync_date: "2026-04-24",
                  latest_success_at: null,
                  expected_business_date: "2026-04-24",
                  primary_action_key: "limit_list_ths.maintain",
                  auto_schedule_status: "none",
                  auto_schedule_total: 0,
                  auto_schedule_active: 0,
                  auto_schedule_next_run_at: null,
                  probe_total: 0,
                  probe_active: 0,
                }),
              ],
            },
          ],
        };
      }
      throw new Error(`unexpected url: ${url}`);
    });

    renderPage();

    expect(await screen.findByText("数据集 · Tushare")).toBeInTheDocument();
    expect(await screen.findByText("股票日线")).toBeInTheDocument();
    expect(await screen.findByText("涨跌停列表（同花顺）")).toBeInTheDocument();
    expect(screen.queryByText("最近同步：2026/04/17 09:10:00")).not.toBeInTheDocument();
    expect(await screen.findByText("最近同步：2026/04/17")).toBeInTheDocument();
    expect(await screen.findByText("最近同步：2026/04/24")).toBeInTheDocument();
    expect(await screen.findAllByText("更新频率：每日")).toHaveLength(3);
    expect(await screen.findByText("raw_tushare.daily")).toBeInTheDocument();
    expect(await screen.findAllByText("正常")).toHaveLength(2);
    expect(await screen.findByText("自动探测")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "去操作" })).toHaveAttribute(
      "href",
      "/app/ops/v21/datasets/tasks?tab=manual&action_key=stk_factor_pro.maintain&action_type=dataset_action",
    );
    const datasetCard = screen.getByText("股票日线").closest("[data-with-border='true']");
    expect(datasetCard).not.toBeNull();
    expect(datasetCard?.className).not.toContain("glass-card");
  });
});
