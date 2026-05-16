import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsV21DatasetAuditPage } from "./ops-v21-dataset-audit-page";

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
      mutations: { retry: false },
    },
  });

  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <OpsV21DatasetAuditPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

function mockApi() {
  apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (path === "/api/v1/ops/review/date-completeness/rules") {
      return {
        summary: { total: 2, supported: 1, unsupported: 1 },
        groups: [
          {
            group_key: "supported",
            group_label: "支持审计",
            items: [
              {
                dataset_key: "moneyflow_ind_dc",
                display_name: "板块资金流向(DC)",
                group_key: "moneyflow",
                group_label: "资金流向",
                group_order: 8,
                item_order: 60,
                domain_key: "board",
                domain_display_name: "板块",
                target_table: "core_serving.board_moneyflow_dc",
                date_axis: "trade_open_day",
                bucket_rule: "every_open_day",
                window_mode: "range",
                input_shape: "trade_date_or_start_end",
                observed_field: "trade_date",
                bucket_window_rule: null,
                bucket_applicability_rule: "always",
                audit_scope: "date_bucket",
                subject_kind: null,
                audit_applicable: true,
                not_applicable_reason: null,
                rule_label: "每个开市交易日",
                data_range: {
                  range_type: "business_date",
                  start_date: "2026-04-01",
                  end_date: "2026-04-24",
                  start_at: null,
                  end_at: null,
                  label: "2026/04/01 至 2026/04/24",
                },
              },
            ],
          },
          {
            group_key: "unsupported",
            group_label: "不支持审计",
            items: [
              {
                dataset_key: "stock_basic",
                display_name: "股票主数据",
                group_key: "reference_data",
                group_label: "A股基础数据",
                group_order: 1,
                item_order: 10,
                domain_key: "reference",
                domain_display_name: "基础主数据",
                target_table: "core_serving.security",
                date_axis: "none",
                bucket_rule: "not_applicable",
                window_mode: "none",
                input_shape: "none",
                observed_field: null,
                bucket_window_rule: null,
                bucket_applicability_rule: "always",
                audit_scope: "date_bucket",
                subject_kind: null,
                audit_applicable: false,
                not_applicable_reason: "snapshot/master dataset",
                rule_label: "不适用日期完整性审计",
                data_range: {
                  range_type: "none",
                  start_date: null,
                  end_date: null,
                  start_at: null,
                  end_at: null,
                  label: "—",
                },
              },
            ],
          },
        ],
      };
    }
    if (path === "/api/v1/ops/review/date-completeness/runs?limit=50&offset=0") {
      return {
        total: 2,
        items: [
          {
            id: 7,
            dataset_key: "stk_period_bar_week",
            display_name: "股票周线行情",
            target_table: "core_serving.stk_period_bar",
            run_mode: "manual",
            run_status: "succeeded",
            result_status: "passed",
            start_date: "2026-01-23",
            end_date: "2026-02-06",
            date_axis: "natural_day",
            bucket_rule: "week_friday",
            window_mode: "range",
            input_shape: "trade_date_or_start_end",
            observed_field: "trade_date",
            bucket_window_rule: "iso_week",
            bucket_applicability_rule: "requires_open_trade_day_in_bucket",
            audit_scope: "date_bucket",
            subject_kind: null,
            expected_bucket_count: 2,
            actual_bucket_count: 3,
            missing_bucket_count: 0,
            excluded_bucket_count: 1,
            gap_range_count: 0,
            expected_cell_count: 0,
            actual_cell_count: 0,
            missing_cell_count: 0,
            affected_bucket_count: 0,
            affected_subject_count: 0,
            detail_truncated: false,
            current_stage: "finished",
            operator_message: "审计通过，已按规则排除 1 个不可产出日期桶。",
            technical_message: null,
            requested_by_user_id: 1,
            schedule_id: null,
            requested_at: "2026-04-30T10:00:00+08:00",
            started_at: "2026-04-30T10:01:00+08:00",
            finished_at: "2026-04-30T10:02:00+08:00",
            created_at: "2026-04-30T10:00:00+08:00",
            updated_at: "2026-04-30T10:02:00+08:00",
          },
          {
            id: 9,
            dataset_key: "adj_factor",
            display_name: "复权因子",
            target_table: "core.equity_adj_factor",
            run_mode: "manual",
            run_status: "succeeded",
            result_status: "failed",
            start_date: "2026-03-30",
            end_date: "2026-03-31",
            date_axis: "trade_open_day",
            bucket_rule: "every_open_day",
            window_mode: "point_or_range",
            input_shape: "trade_date_or_start_end",
            observed_field: "trade_date",
            bucket_window_rule: "none",
            bucket_applicability_rule: "always",
            audit_scope: "date_subject_matrix",
            subject_kind: "stock",
            expected_bucket_count: 2,
            actual_bucket_count: 2,
            missing_bucket_count: 0,
            excluded_bucket_count: 0,
            gap_range_count: 0,
            expected_cell_count: 5,
            actual_cell_count: 3,
            missing_cell_count: 2,
            affected_bucket_count: 2,
            affected_subject_count: 1,
            detail_truncated: false,
            current_stage: "finished",
            operator_message: "审计发现对象矩阵缺口。",
            technical_message: null,
            requested_by_user_id: 1,
            schedule_id: null,
            requested_at: "2026-04-30T10:05:00+08:00",
            started_at: "2026-04-30T10:06:00+08:00",
            finished_at: "2026-04-30T10:07:00+08:00",
            created_at: "2026-04-30T10:05:00+08:00",
            updated_at: "2026-04-30T10:07:00+08:00",
          },
        ],
      };
    }
    if (path === "/api/v1/ops/review/date-completeness/runs" && options?.method === "POST") {
      return {
        id: 8,
        run_status: "queued",
        dataset_key: "moneyflow_ind_dc",
        display_name: "板块资金流向(DC)",
        start_date: "2026-04-20",
        end_date: "2026-04-24",
        requested_at: "2026-04-30T10:03:00+08:00",
      };
    }
    if (path === "/api/v1/ops/review/date-completeness/runs/7/gaps") {
      return { total: 0, items: [] };
    }
    if (path === "/api/v1/ops/review/date-completeness/runs/7/exclusions") {
      return {
        total: 1,
        items: [
          {
            id: 11,
            run_id: 7,
            dataset_key: "stk_period_bar_week",
            bucket_kind: "natural_date",
            bucket_value: "2026-01-30",
            window_start: "2026-01-26",
            window_end: "2026-02-01",
            reason_code: "bucket_has_no_open_trade_day",
            reason_message: "该自然周内没有开市交易日，不应产出周线数据。",
            created_at: "2026-04-30T10:02:00+08:00",
          },
        ],
      };
    }
    if (path === "/api/v1/ops/review/date-completeness/runs/9/subject-gaps") {
      return {
        total: 2,
        items: [
          {
            id: 21,
            run_id: 9,
            dataset_key: "adj_factor",
            bucket_kind: "trade_date",
            bucket_value: "2026-03-30",
            subject_kind: "stock",
            subject_key_fields: ["ts_code"],
            actual_key_fields: ["ts_code", "trade_date"],
            missing_cell_count: 1,
            affected_subject_count: 1,
            sample_subjects: [{ subject_key: "001257.SZ", subject_name: "立新能源" }],
            created_at: "2026-04-30T10:07:00+08:00",
          },
        ],
      };
    }
    if (path === "/api/v1/ops/review/date-completeness/runs/9/subject-gap-details") {
      return {
        total: 2,
        items: [
          {
            id: 31,
            run_id: 9,
            gap_id: 21,
            dataset_key: "adj_factor",
            bucket_kind: "trade_date",
            bucket_value: "2026-03-30",
            subject_kind: "stock",
            subject_key: "001257.SZ",
            subject_name: "立新能源",
            subject_key_json: { ts_code: "001257.SZ" },
            actual_key_json: { ts_code: "001257.SZ", trade_date: "2026-03-30" },
            lifecycle_start: "2022-07-27",
            lifecycle_end: null,
            reason_code: "missing_subject_bucket",
            reason_message: "该对象在该日期桶处于有效生命周期内，但目标表缺少对应行。",
            target_table: "core.equity_adj_factor",
            created_at: "2026-04-30T10:07:00+08:00",
          },
        ],
      };
    }
    if (path === "/api/v1/ops/review/date-completeness/schedules?limit=50&offset=0") {
      return { total: 0, items: [] };
    }
    if (path === "/api/v1/ops/review/date-completeness/schedules" && options?.method === "POST") {
      return {
        id: 3,
        dataset_key: "moneyflow_ind_dc",
        display_name: "板块资金流向(DC) 日期完整性审计",
        status: "active",
        window_mode: "rolling",
        start_date: null,
        end_date: null,
        lookback_count: 10,
        lookback_unit: "open_day",
        calendar_scope: "default_cn_market",
        calendar_exchange: null,
        cron_expr: "0 22 * * *",
        timezone: "Asia/Shanghai",
        next_run_at: "2026-04-30T14:00:00Z",
        last_run_id: null,
        last_run_status: null,
        last_result_status: null,
        last_run_finished_at: null,
        created_by_user_id: 1,
        updated_by_user_id: 1,
        created_at: "2026-04-30T10:00:00+08:00",
        updated_at: "2026-04-30T10:00:00+08:00",
      };
    }
    throw new Error(`unexpected path: ${path}`);
  });
}

describe("数据集审计页", () => {
  beforeEach(() => {
    apiRequest.mockReset();
    mockApi();
  });

  it("展示支持和不支持审计的数据集，并使用独立审计 API 创建 run", async () => {
    renderPage();

    expect(await screen.findByText("数据集审计")).toBeInTheDocument();
    expect((await screen.findAllByText("板块资金流向(DC)")).length).toBeGreaterThan(0);
    expect(await screen.findByText("每个开市交易日")).toBeInTheDocument();
    expect(await screen.findByText("数据时间范围")).toBeInTheDocument();
    expect(await screen.findByText("2026/04/01 至 2026/04/24")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "创建审计" }));
    await screen.findByText("审计说明");
    const createButtons = screen.getAllByRole("button", { name: "创建审计" });
    fireEvent.click(createButtons[createButtons.length - 1]);

    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/review/date-completeness/runs", {
        method: "POST",
        body: {
          dataset_key: "moneyflow_ind_dc",
          start_date: "2026-04-20",
          end_date: "2026-04-24",
        },
      });
    });
    expect(apiRequest.mock.calls.some(([path]) => String(path).includes("/api/v1/ops/task-runs"))).toBe(false);
  });

  it("在自动审计页创建独立 schedule，不复用任务中心接口", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: /自动审计/ }));
    fireEvent.click(await screen.findByRole("button", { name: "创建自动审计" }));
    await screen.findByText("日历：默认 A 股交易日历。港股/自定义交易所入口已预留，后续按业务口径开启。");
    fireEvent.click(screen.getByRole("button", { name: "确认创建自动审计" }));

    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/review/date-completeness/schedules", {
        method: "POST",
        body: {
          dataset_key: "moneyflow_ind_dc",
          display_name: null,
          status: "active",
          window_mode: "rolling",
          start_date: null,
          end_date: null,
          lookback_count: 10,
          lookback_unit: "open_day",
          calendar_scope: "default_cn_market",
          calendar_exchange: null,
          cron_expr: "0 22 * * *",
          timezone: "Asia/Shanghai",
        },
      });
    });
    expect(apiRequest.mock.calls.some(([path]) => String(path).includes("/api/v1/ops/task-runs"))).toBe(false);
  });

  it("展示规则排除桶明细，不把长假周误报成缺失", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: /审计记录/ }));
    expect((await screen.findAllByText("已完成")).length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByText("存在 1 个非预期日期桶")).toBeInTheDocument();
    const detailButtons = await screen.findAllByRole("button", { name: "查看详情" });
    fireEvent.click(detailButtons[0]);

    expect(await screen.findByText("发现非预期日期桶")).toBeInTheDocument();
    expect((await screen.findAllByText("规则排除")).length).toBeGreaterThanOrEqual(2);
    expect(await screen.findByText("2026/01/30")).toBeInTheDocument();
    expect(await screen.findByText("2026/01/26 至 2026/02/01")).toBeInTheDocument();
    expect(await screen.findByText("该自然周内没有开市交易日，不应产出周线数据。")).toBeInTheDocument();
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/review/date-completeness/runs/7/exclusions");
    });
  });

  it("展示对象矩阵审计摘要和缺失对象样例", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: /审计记录/ }));
    expect(await screen.findByText("复权因子")).toBeInTheDocument();
    const detailButtons = await screen.findAllByRole("button", { name: "查看详情" });
    fireEvent.click(detailButtons[1]);

    expect(await screen.findByText("对象缺失摘要")).toBeInTheDocument();
    expect(await screen.findByText("对象缺失样例明细")).toBeInTheDocument();
    expect(await screen.findByText("审计粒度：日期 × 对象矩阵")).toBeInTheDocument();
    expect(await screen.findByText("对象类型：stock")).toBeInTheDocument();
    expect((await screen.findAllByText("001257.SZ 立新能源")).length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByText("ts_code=001257.SZ，trade_date=2026-03-30")).toBeInTheDocument();
    expect(await screen.findByText("2022/07/27 至今")).toBeInTheDocument();
    expect(await screen.findByText("该对象在该日期桶处于有效生命周期内，但目标表缺少对应行。")).toBeInTheDocument();

    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/review/date-completeness/runs/9/subject-gaps");
      expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/review/date-completeness/runs/9/subject-gap-details");
    });
    expect(apiRequest.mock.calls.some(([path]) => String(path).includes("/runs/9/gaps"))).toBe(false);
  });
});
