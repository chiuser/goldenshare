import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { OpsTaskDetailPage } from "./ops-task-detail-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
}));

function createTaskRunView(status = "failed") {
  const hasIssue = status === "failed" || status === "partial_success";
  return {
    run: {
      id: 1,
      task_type: "dataset_action",
      resource_key: "daily",
      source_key: "tushare",
      action: "maintain",
      title: "股票日线",
      trigger_source: "manual",
      status,
      status_reason_code: status === "failed" ? "ingestion_failed" : null,
      requested_by_username: "admin",
      schedule_display_name: null,
      time_input: {
        mode: "range",
        start_date: "2026-03-23",
        end_date: "2026-03-30",
      },
      filters: {},
      time_scope: {
        kind: "range",
        start: "2026-03-23",
        end: "2026-03-30",
        label: "2026-03-23 ~ 2026-03-30",
      },
      time_scope_label: "2026-03-23 ~ 2026-03-30",
      requested_at: "2026-03-31T01:00:00Z",
      queued_at: "2026-03-31T01:00:01Z",
      started_at: "2026-03-31T01:00:02Z",
      ended_at: null,
      cancel_requested_at: null,
      canceled_at: null,
    },
    progress: {
      unit_total: 5814,
      unit_done: 651,
      unit_failed: 1,
      progress_percent: 11,
      rows_fetched: 6,
      rows_saved: 5,
      rows_rejected: 1,
      rejected_reason_counts: {
        "normalize.required_field_missing:trade_date": 1,
      },
      rejected_reasons: [
        {
          reason_key: "normalize.required_field_missing:trade_date",
          reason_code: "normalize.required_field_missing",
          field: "trade_date",
          count: 1,
          label: "必填字段缺失",
          suggested_action: "检查字段映射和空值处理",
        },
      ],
      current_object:
        status === "running"
          ? {
              title: "正在处理：美欣达（002034.SZ）",
              description: "处理范围：2026-03-23 ~ 2026-03-30；频率：1min",
              fields: [
                { label: "证券代码", value: "002034.SZ" },
                { label: "证券名称", value: "美欣达" },
              ],
            }
          : null,
    },
    primary_issue: hasIssue
      ? {
          id: 99,
          severity: "error",
          code: "ingestion_failed",
          title: "任务处理失败",
          operator_message: "任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
          suggested_action: "先确认已保存数据和失败位置，再决定是否缩小范围重新提交。",
          object: {
            title: "问题位置：美欣达（002034.SZ）",
            description: "处理范围：2026-03-23 ~ 2026-03-30；频率：1min",
            fields: [
              { label: "证券代码", value: "002034.SZ" },
              { label: "证券名称", value: "美欣达" },
            ],
          },
          has_technical_detail: true,
          occurred_at: "2026-03-31T01:00:05Z",
        }
      : null,
    nodes: [
      {
        id: 10,
        parent_node_id: null,
        node_key: "daily:2026-03-23:2026-03-30",
        node_type: "dataset_plan",
        sequence_no: 1,
        title: "维护 股票日线",
        resource_key: "daily",
        status: hasIssue ? "failed" : status,
        time_input: {
          mode: "range",
          start_date: "2026-03-23",
          end_date: "2026-03-30",
        },
        context: {},
        rows_fetched: 6,
        rows_saved: 5,
        rows_rejected: 1,
        rejected_reason_counts: {
          "normalize.required_field_missing:trade_date": 1,
        },
        rejected_reasons: [
          {
            reason_key: "normalize.required_field_missing:trade_date",
            reason_code: "normalize.required_field_missing",
            field: "trade_date",
            count: 1,
            label: "必填字段缺失",
            suggested_action: "检查字段映射和空值处理",
          },
        ],
        issue_id: hasIssue ? 99 : null,
        started_at: "2026-03-31T01:00:02Z",
        ended_at: null,
        duration_ms: null,
      },
    ],
    node_total: 1,
    nodes_truncated: false,
    actions: {
      can_retry: hasIssue,
      can_cancel: false,
      can_copy_params: true,
    },
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const rootRoute = createRootRoute({
    component: () => <OpsTaskDetailPage taskRunId={1} />,
  });
  const route = createRoute({
    getParentRoute: () => rootRoute,
    path: "/ops/tasks/$taskRunId",
    component: () => <OpsTaskDetailPage taskRunId={1} />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([route]),
    basepath: "/app",
    history: createMemoryHistory({ initialEntries: ["/app/ops/tasks/1"] }),
  });

  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("任务详情页", () => {
  it("只读取 TaskRun view API，并将失败原因集中展示一次", async () => {
    const user = userEvent.setup();
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/task-runs/1/view") {
        return createTaskRunView();
      }
      if (path === "/api/v1/ops/task-runs/1/issues/99") {
        return {
          id: 99,
          task_run_id: 1,
          node_id: 10,
          severity: "error",
          code: "ingestion_failed",
          title: "任务处理失败",
          operator_message: "任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
          suggested_action: "先确认已保存数据和失败位置，再决定是否缩小范围重新提交。",
          object: {
            title: "问题位置：美欣达（002034.SZ）",
            description: "处理范围：2026-03-23 ~ 2026-03-30；频率：1min",
            fields: [],
          },
          technical_message: "psycopg.errors.UniqueViolation",
          technical_payload: {
            source_phase: "execute",
            node_id: 10,
          },
          source_phase: "execute",
          occurred_at: "2026-03-31T01:00:05Z",
        };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("先看当前状态、处理范围和进度，再决定返回任务记录、复制参数或重新提交。")).toBeInTheDocument();
    expect(await screen.findByText("股票日线")).toBeInTheDocument();
    expect(await screen.findByText("处理范围")).toBeInTheDocument();
    expect(await screen.findByText("2026-03-23 ~ 2026-03-30")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新提交" })).toBeInTheDocument();
    expect(await screen.findByText("任务未完全完成")).toBeInTheDocument();
    expect(await screen.findByText("失败原因")).toBeInTheDocument();
    expect(screen.getAllByText("任务处理失败")).toHaveLength(1);
    expect(await screen.findByText("当前进度")).toBeInTheDocument();
    expect(await screen.findByText("651 / 5814")).toBeInTheDocument();
    expect(screen.queryByText("暂无当前对象")).not.toBeInTheDocument();
    expect(screen.queryByText(/当前对象：/)).not.toBeInTheDocument();
    expect(await screen.findByText(/问题位置：美欣达（002034\.SZ）/)).toBeInTheDocument();
    expect(await screen.findByText("执行过程")).toBeInTheDocument();
    expect(await screen.findByText("读取 6，保存 5，拒绝 1")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "查看原因" }));

    expect(await screen.findByText("拒绝原因详情")).toBeInTheDocument();
    expect(await screen.findByText("必填字段缺失")).toBeInTheDocument();
    expect(await screen.findByText("trade_date")).toBeInTheDocument();
    expect(await screen.findByText(/检查字段映射和空值处理/)).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "查看技术诊断" }));

    expect(await screen.findByText("完整技术错误")).toBeInTheDocument();
    expect(await screen.findByText("psycopg.errors.UniqueViolation")).toBeInTheDocument();
    expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/task-runs/1/view");
    expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/task-runs/1/issues/99");
  });

  it("成功态不展示失败原因和技术诊断入口", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/task-runs/1/view") {
        return createTaskRunView("success");
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("任务处理完成")).toBeInTheDocument();
    expect(await screen.findByText("本次任务已经结束，处理结果已保存。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新提交" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回卡片页" })).toHaveAttribute(
      "href",
      "/app/ops/v21/datasets/tushare",
    );
    expect(screen.queryByText("失败原因")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查看技术诊断" })).not.toBeInTheDocument();
  });
});
