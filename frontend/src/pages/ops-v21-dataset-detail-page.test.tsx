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

function datasetCardsPayload() {
  return {
    total: 1,
    groups: [
      {
        domain_key: "equity",
        domain_display_name: "股票",
        items: [
          {
            card_key: "daily",
            dataset_key: "daily",
            detail_dataset_key: "daily",
            resource_key: "daily",
            display_name: "股票日线",
            primary_action_key: "daily.maintain",
            stage_statuses: [
              {
                stage: "raw",
                stage_label: "原始层",
                table_name: "raw_tushare.daily",
                source_key: "tushare",
                source_display_name: "Tushare",
                status: "success",
                rows_in: 120,
                rows_out: 120,
                error_count: null,
                lag_seconds: null,
                message: null,
                calculated_at: "2026-04-17T09:10:00+08:00",
                last_success_at: "2026-04-17T09:10:00+08:00",
                last_failure_at: null,
              },
              {
                stage: "std",
                stage_label: "标准层",
                table_name: "core.daily",
                source_key: null,
                source_display_name: null,
                status: "warning",
                rows_in: 120,
                rows_out: 118,
                error_count: 1,
                lag_seconds: 1200,
                message: null,
                calculated_at: "2026-04-17T09:20:00+08:00",
                last_success_at: "2026-04-17T09:20:00+08:00",
                last_failure_at: null,
              },
              {
                stage: "serving",
                stage_label: "服务层",
                table_name: "core_serving.daily",
                source_key: null,
                source_display_name: null,
                status: "success",
                rows_in: 120,
                rows_out: 120,
                error_count: null,
                lag_seconds: 1800,
                message: null,
                calculated_at: "2026-04-17T09:30:00+08:00",
                last_success_at: "2026-04-17T09:30:00+08:00",
                last_failure_at: null,
              },
            ],
            raw_sources: [
              {
                source_key: "tushare",
                source_display_name: "Tushare",
                table_name: "raw_tushare.daily",
                status: "success",
                calculated_at: "2026-04-17T09:10:00+08:00",
              },
            ],
          },
        ],
      },
    ],
  };
}

function datasetCardsWithoutCurrentRuntimePayload() {
  const payload = datasetCardsPayload();
  return {
    ...payload,
    groups: payload.groups.map((group) => ({
      ...group,
      items: group.items.map((item) => ({
        ...item,
        stage_statuses: item.stage_statuses.map((stage) => ({
          ...stage,
          status: "unknown",
          rows_in: null,
          rows_out: null,
          error_count: null,
          lag_seconds: null,
          calculated_at: null,
          last_success_at: null,
          last_failure_at: null,
        })),
        raw_sources: [],
      })),
    })),
  };
}

describe("V2.1 数据集详情页", () => {
  it("使用统一指标面板和数据表展示详情状态与执行记录", async () => {
    apiRequest.mockImplementation(async (url: string) => {
      if (url === "/api/v1/ops/dataset-cards?limit=2000") {
        return datasetCardsPayload();
      }
      if (url === "/api/v1/ops/layer-snapshots/history?dataset_key=daily&limit=50") {
        return {
          total: 12,
          items: [],
        };
      }
      if (url === "/api/v1/ops/task-runs?resource_key=daily&limit=20") {
        return {
          total: 1,
          items: [
            {
              id: 101,
              task_type: "dataset_action",
              resource_key: "daily",
              action: "maintain",
              title: "股票日线",
              time_scope: null,
              time_scope_label: null,
              schedule_display_name: null,
              trigger_source: "manual",
              status: "success",
              requested_by_username: "admin",
              requested_at: "2026-04-17T09:00:00+08:00",
              started_at: "2026-04-17T09:00:02+08:00",
              ended_at: "2026-04-17T09:03:00+08:00",
              unit_total: 1,
              unit_done: 1,
              unit_failed: 0,
              rows_fetched: 120,
              rows_saved: 120,
              rows_rejected: 0,
              progress_percent: 100,
              primary_issue_id: null,
              primary_issue_title: null,
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
              dataset_display_name: "股票日线",
              source_key: "tushare",
              source_display_name: "Tushare",
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
              dataset_display_name: "股票日线",
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

    expect(await screen.findByText("股票日线")).toBeInTheDocument();
    expect(await screen.findByText("全链路层级状态")).toBeInTheDocument();
    expect(await screen.findByText("数据来源状态")).toBeInTheDocument();
    expect(await screen.findByText("近期任务记录")).toBeInTheDocument();
    expect(await screen.findByText("策略 v3")).toBeInTheDocument();
    expect(await screen.findByText("101")).toBeInTheDocument();
    expect(await screen.findByText("Tushare")).toBeInTheDocument();
    expect(screen.queryByText("daily · 股票日线")).not.toBeInTheDocument();
    expect(screen.queryByText("tushare")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "去处理" })).toHaveAttribute(
      "href",
      "/app/ops/v21/datasets/tasks?tab=manual&action_key=daily.maintain&action_type=dataset_action",
    );
    expect(screen.getByRole("link", { name: "手动执行" })).toHaveAttribute(
      "href",
      "/app/ops/v21/datasets/tasks?tab=manual&action_key=daily.maintain&action_type=dataset_action",
    );
  });

  it("没有 layer snapshot 时不再用 freshness 伪造层级状态", async () => {
    apiRequest.mockImplementation(async (url: string) => {
      if (url === "/api/v1/ops/dataset-cards?limit=2000") {
        return datasetCardsWithoutCurrentRuntimePayload();
      }
      if (url === "/api/v1/ops/layer-snapshots/history?dataset_key=daily&limit=50") {
        return { total: 0, items: [] };
      }
      if (url === "/api/v1/ops/task-runs?resource_key=daily&limit=20") {
        return { total: 0, items: [] };
      }
      if (url === "/api/v1/ops/probes?dataset_key=daily&limit=20") {
        return { total: 0, items: [] };
      }
      if (url === "/api/v1/ops/releases?dataset_key=daily&limit=20") {
        return { total: 0, items: [] };
      }
      if (url === "/api/v1/ops/std-rules/mapping?dataset_key=daily&limit=100") {
        return { total: 0, items: [] };
      }
      if (url === "/api/v1/ops/std-rules/cleansing?dataset_key=daily&limit=100") {
        return { total: 0, items: [] };
      }
      throw new Error(`unexpected url: ${url}`);
    });

    renderPage();

    expect(await screen.findByText("全链路层级状态")).toBeInTheDocument();
    expect(screen.queryByText(/最近成功：2026\/04\/17/)).not.toBeInTheDocument();
  });
});
