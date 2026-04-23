import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsSourceManagementPage } from "./ops-source-management-page";

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
        <OpsSourceManagementPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("数据源管理（新版）", () => {
  it("桥接页可以展示探测、发布、规则与分层快照", async () => {
    apiRequest.mockResolvedValueOnce({
      summary: {
        probe_total: 1,
        probe_active: 1,
        release_total: 1,
        release_running: 1,
        std_mapping_total: 1,
        std_mapping_active: 1,
        std_cleansing_total: 1,
        std_cleansing_active: 1,
        layer_latest_total: 1,
        layer_latest_failed: 0,
      },
      probe_rules: [
        {
          id: 1,
          name: "收盘后探测",
          dataset_key: "equity_daily",
          source_key: "tushare",
          status: "active",
          probe_interval_seconds: 180,
          last_probed_at: "2026-04-14T08:00:00Z",
          last_triggered_at: "2026-04-14T08:01:00Z",
          created_at: "2026-04-14T08:00:00Z",
          updated_at: "2026-04-14T08:01:00Z",
        },
      ],
      releases: [
        {
          id: 11,
          dataset_key: "security_master",
          target_policy_version: 3,
          status: "running",
          triggered_by_username: "admin",
          triggered_at: "2026-04-14T08:02:00Z",
          finished_at: null,
          rollback_to_release_id: null,
          created_at: "2026-04-14T08:02:00Z",
          updated_at: "2026-04-14T08:02:00Z",
        },
      ],
      std_mapping_rules: [
        {
          id: 21,
          dataset_key: "security_master",
          source_key: "biying",
          src_field: "dm",
          std_field: "ts_code",
          src_type: null,
          std_type: null,
          transform_fn: "normalize_stock_code",
          lineage_preserved: true,
          status: "active",
          rule_set_version: 2,
          created_at: "2026-04-14T08:03:00Z",
          updated_at: "2026-04-14T08:03:00Z",
        },
      ],
      std_cleansing_rules: [
        {
          id: 31,
          dataset_key: "security_master",
          source_key: "biying",
          rule_type: "required_fields",
          target_fields_json: ["ts_code"],
          condition_expr: null,
          action: "drop_row",
          status: "active",
          rule_set_version: 1,
          created_at: "2026-04-14T08:04:00Z",
          updated_at: "2026-04-14T08:04:00Z",
        },
      ],
      layer_latest: [
        {
          snapshot_date: "2026-04-14",
          dataset_key: "equity_daily",
          source_key: "tushare",
          stage: "serving",
          status: "healthy",
          rows_in: 100,
          rows_out: 100,
          error_count: 0,
          last_success_at: "2026-04-14T08:05:00Z",
          last_failure_at: null,
          lag_seconds: 120,
          message: null,
          calculated_at: "2026-04-14T08:05:00Z",
        },
      ],
    });

    renderPage();

    expect(await screen.findByText("数据源管理")).toBeInTheDocument();
    expect(await screen.findByText("桥接看板摘要")).toBeInTheDocument();
    expect(await screen.findByText("探测规则（Probe）")).toBeInTheDocument();
    expect(await screen.findByText("发布流水（Resolution Release）")).toBeInTheDocument();
    expect(await screen.findByText("标准化映射规则（Mapping）")).toBeInTheDocument();
    expect(await screen.findByText("标准化清洗规则（Cleansing）")).toBeInTheDocument();
    expect(await screen.findByText("分层快照（Latest）")).toBeInTheDocument();
    expect(screen.queryByText("原始层")).not.toBeInTheDocument();
    expect(await screen.findByText("服务层")).toBeInTheDocument();
  });
});
