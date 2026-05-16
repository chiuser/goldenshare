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

function renderPage(
  props: {
    sourceKey?: "tushare" | "biying" | "biz_tableset";
    title?: string;
    description?: string;
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <OpsV21SourcePage
          sourceKey={props.sourceKey || "tushare"}
          title={props.title || "数据集 · Tushare"}
          description={props.description}
        />
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
    freshness_policy: "continuous_open_day",
    raw_table: "raw_tushare.daily",
    raw_table_label: "raw_tushare.daily",
    target_table: "core_serving.daily",
    latest_business_date: "2026-04-17",
    earliest_business_date: "2026-04-01",
    last_sync_date: "2026-04-17",
    latest_success_at: "2026-04-17T09:10:00+08:00",
    expected_business_date: "2026-04-17",
    latest_observed_date: "2026-04-17",
    latest_observed_date_label: "最新业务日期",
    expected_observed_date: "2026-04-17",
    expected_observed_date_label: "应完成业务日期",
    last_success_label: "最近维护成功时间",
    lag_days: 0,
    freshness_note: null,
    primary_action_key: "daily.maintain",
    active_task_run_status: null,
    active_task_run_started_at: null,
    auto_schedule_status: "active",
    auto_schedule_total: 1,
    auto_schedule_active: 1,
    auto_schedule_next_run_at: "2026-04-18T16:00:00+08:00",
    probe_total: 1,
    probe_active: 1,
    std_mapping_configured: true,
    std_cleansing_configured: true,
    resolution_policy_configured: true,
    ...overrides,
  };
}

describe("V2.1 数据源详情页", () => {
  it("消费 dataset card view 展示数据集健康状态", async () => {
    apiRequest.mockImplementation(async (url: string) => {
      if (url === "/api/v1/ops/dataset-cards?source_key=tushare") {
        return {
          total: 3,
          groups: [
            {
              group_key: "equity_market",
              group_label: "A股行情",
              group_order: 2,
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
                  latest_observed_date: "2026-04-16",
                  expected_observed_date: "2026-04-17",
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
              group_key: "limit_board",
              group_label: "涨跌停榜",
              group_order: 5,
              items: [
                card({
                  card_key: "limit_list_ths",
                  dataset_key: "limit_list_ths",
                  detail_dataset_key: "limit_list_ths",
                  resource_key: "limit_list_ths",
                  display_name: "涨跌停列表（同花顺）",
                  group_key: "limit_board",
                  group_label: "涨跌停榜",
                  group_order: 5,
                  item_order: 10,
                  domain_key: "market",
                  domain_display_name: "行情",
                  raw_table: "raw_tushare.limit_list_ths",
                  raw_table_label: "raw_tushare.limit_list_ths",
                  latest_business_date: "2026-04-24",
                  earliest_business_date: "2026-04-24",
                  last_sync_date: "2026-04-24",
                  latest_success_at: null,
                  expected_business_date: "2026-04-24",
                  latest_observed_date: "2026-04-24",
                  expected_observed_date: "2026-04-24",
                  last_success_label: null,
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
    expect(await screen.findByText("最近维护成功时间：2026/04/17 09:10:00")).toBeInTheDocument();
    expect(await screen.findByText("最新业务日期：2026/04/24")).toBeInTheDocument();
    expect(screen.queryByText("更新频率：每日")).not.toBeInTheDocument();
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

  it("将 stale 显示为严重滞后，而不是失败", async () => {
    apiRequest.mockImplementation(async (url: string) => {
      if (url === "/api/v1/ops/dataset-cards?source_key=tushare") {
        return {
          total: 1,
          groups: [
            {
              group_key: "reference_data",
              group_label: "A股基础数据",
              group_order: 1,
              items: [
                card({
                  card_key: "namechange",
                  dataset_key: "namechange",
                  detail_dataset_key: "namechange",
                  resource_key: "namechange",
                  display_name: "股票曾用名",
                  group_key: "reference_data",
                  group_label: "A股基础数据",
                  group_order: 1,
                  item_order: 20,
                  status: "stale",
                  freshness_status: "stale",
                  raw_table: "raw_tushare.namechange",
                  raw_table_label: "raw_tushare.namechange",
                  latest_business_date: "2026-04-30",
                  earliest_business_date: "1991-04-03",
                  last_sync_date: "2026-05-05",
                  latest_success_at: "2026-05-05T22:14:27+08:00",
                  expected_business_date: "2026-05-05",
                  latest_observed_date: "2026-04-30",
                  expected_observed_date: "2026-05-05",
                  lag_days: 5,
                  primary_action_key: "namechange.maintain",
                  auto_schedule_status: "active",
                  auto_schedule_total: 1,
                  auto_schedule_active: 1,
                  auto_schedule_next_run_at: "2026-05-06T00:10:00+08:00",
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

    expect(await screen.findByText("股票曾用名")).toBeInTheDocument();
    expect(await screen.findByText("严重滞后")).toBeInTheDocument();
    expect(screen.queryByText("失败")).not.toBeInTheDocument();
  });

  it("支持 Biz 数据集只读卡片展示", async () => {
    apiRequest.mockImplementation(async (url: string) => {
      if (url === "/api/v1/ops/dataset-cards?source_key=biz_tableset") {
        return {
          total: 1,
          groups: [
            {
              group_key: "wealth_market",
              group_label: "财势乾坤",
              group_order: 90,
              items: [
                card({
                  card_key: "wealth_market_turnover_snapshot",
                  dataset_key: "wealth_market_turnover_snapshot",
                  detail_dataset_key: "wealth_market_turnover_snapshot",
                  resource_key: "wealth_market_turnover_snapshot",
                  display_name: "成交额分钟快照",
                  group_key: "wealth_market",
                  group_label: "财势乾坤",
                  group_order: 90,
                  item_order: 10,
                  domain_key: "biz_tableset",
                  domain_display_name: "Biz数据集",
                  delivery_mode: "biz_table_snapshot",
                  delivery_mode_label: "业务派生表",
                  delivery_mode_tone: "info",
                  layer_plan: "biz_tableset",
                  freshness_policy: "continuous_open_day",
                  raw_table: null,
                  raw_table_label: null,
                  target_table: "core_serving.wealth_market_turnover_snapshot",
                  latest_business_date: "2026-05-08",
                  earliest_business_date: "2026-05-08",
                  latest_observed_at: "2026-05-08T15:00:00",
                  latest_success_at: "2026-05-08T20:10:00+08:00",
                  last_sync_date: null,
                  expected_business_date: "2026-05-08",
                  latest_observed_date: "2026-05-08",
                  latest_observed_date_label: "最新业务日期",
                  expected_observed_date: "2026-05-08",
                  expected_observed_date_label: "应完成业务日期",
                  last_success_label: "最近构建成功时间",
                  primary_action_key: null,
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

    renderPage({
      sourceKey: "biz_tableset",
      title: "数据集 · Biz数据集",
      description: "展示本系统自建业务派生表的只读状态。暂不提供写入和调度入口。",
    });

    expect(await screen.findByText("数据集 · Biz数据集")).toBeInTheDocument();
    expect(await screen.findByText("成交额分钟快照")).toBeInTheDocument();
    expect(await screen.findByText("core_serving.wealth_market_turnover_snapshot")).toBeInTheDocument();
    expect(await screen.findByText("最近构建成功时间：2026/05/08 20:10:00")).toBeInTheDocument();
    expect(await screen.findByText("只读展示")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "去操作" })).not.toBeInTheDocument();
    expect(screen.queryByText("未配置自动更新")).not.toBeInTheDocument();
  });
});
