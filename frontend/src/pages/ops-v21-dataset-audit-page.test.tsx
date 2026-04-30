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
                domain_key: "board",
                domain_display_name: "板块",
                target_table: "core_serving.board_moneyflow_dc",
                date_axis: "trade_open_day",
                bucket_rule: "every_open_day",
                window_mode: "range",
                input_shape: "trade_date_or_start_end",
                observed_field: "trade_date",
                audit_applicable: true,
                not_applicable_reason: null,
                rule_label: "每个开市交易日",
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
                domain_key: "reference",
                domain_display_name: "基础主数据",
                target_table: "core_serving.security",
                date_axis: "none",
                bucket_rule: "not_applicable",
                window_mode: "none",
                input_shape: "none",
                observed_field: null,
                audit_applicable: false,
                not_applicable_reason: "snapshot/master dataset",
                rule_label: "不适用日期完整性审计",
              },
            ],
          },
        ],
      };
    }
    if (path === "/api/v1/ops/review/date-completeness/runs?limit=50&offset=0") {
      return {
        total: 1,
        items: [
          {
            id: 7,
            dataset_key: "moneyflow_ind_dc",
            display_name: "板块资金流向(DC)",
            target_table: "core_serving.board_moneyflow_dc",
            run_mode: "manual",
            run_status: "succeeded",
            result_status: "passed",
            start_date: "2026-04-20",
            end_date: "2026-04-24",
            date_axis: "trade_open_day",
            bucket_rule: "every_open_day",
            window_mode: "range",
            input_shape: "trade_date_or_start_end",
            observed_field: "trade_date",
            expected_bucket_count: 5,
            actual_bucket_count: 5,
            missing_bucket_count: 0,
            gap_range_count: 0,
            current_stage: "finished",
            operator_message: "审计通过，未发现日期缺口。",
            technical_message: null,
            requested_by_user_id: 1,
            schedule_id: null,
            requested_at: "2026-04-30T10:00:00+08:00",
            started_at: "2026-04-30T10:01:00+08:00",
            finished_at: "2026-04-30T10:02:00+08:00",
            created_at: "2026-04-30T10:00:00+08:00",
            updated_at: "2026-04-30T10:02:00+08:00",
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
});
