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
  return {
    run: {
      id: 1,
      task_type: "dataset_action",
      resource_key: "daily",
      action: "maintain",
      title: "股票日线",
      trigger_source: "manual",
      status,
      status_reason_code: status === "failed" ? "execution_failed" : null,
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
      current_context: {
        ts_code: "002034.SZ",
        security_name: "美欣达",
        freq: "1min",
      },
    },
    primary_issue: {
      id: 99,
      severity: "error",
      code: "execution_failed",
      title: "任务处理失败",
      operator_message: "任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
      suggested_action: "先确认已保存数据和失败位置，再决定是否缩小范围重新提交。",
      has_technical_detail: true,
      occurred_at: "2026-03-31T01:00:05Z",
    },
    nodes: [
      {
        id: 10,
        parent_node_id: null,
        node_key: "daily:2026-03-23:2026-03-30",
        node_type: "dataset_plan",
        sequence_no: 1,
        title: "维护 股票日线",
        resource_key: "daily",
        status: "failed",
        time_input: {
          mode: "range",
          start_date: "2026-03-23",
          end_date: "2026-03-30",
        },
        context: {},
        rows_fetched: 6,
        rows_saved: 5,
        rows_rejected: 1,
        issue_id: 99,
        started_at: "2026-03-31T01:00:02Z",
        ended_at: null,
        duration_ms: null,
      },
    ],
    node_total: 1,
    nodes_truncated: false,
    actions: {
      can_retry: true,
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
          code: "execution_failed",
          title: "任务处理失败",
          operator_message: "任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
          suggested_action: "先确认已保存数据和失败位置，再决定是否缩小范围重新提交。",
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

    expect(await screen.findByText("当前详情页只读取 TaskRun view API，主页面只展示一处失败原因。")).toBeInTheDocument();
    expect(await screen.findByText("股票日线")).toBeInTheDocument();
    expect(await screen.findByText("处理范围")).toBeInTheDocument();
    expect(await screen.findByText("2026-03-23 ~ 2026-03-30")).toBeInTheDocument();
    expect(await screen.findByText("失败原因")).toBeInTheDocument();
    expect(screen.getAllByText("任务处理失败")).toHaveLength(2);
    expect(await screen.findByText("当前进度")).toBeInTheDocument();
    expect(await screen.findByText("651 / 5814")).toBeInTheDocument();
    expect(await screen.findByText("当前对象：ts_code=002034.SZ，security_name=美欣达，freq=1min")).toBeInTheDocument();
    expect(await screen.findByText("执行过程")).toBeInTheDocument();
    expect(await screen.findByText("读取 6，保存 5，拒绝 1")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "查看技术诊断" }));

    expect(await screen.findByText("完整技术错误")).toBeInTheDocument();
    expect(await screen.findByText("psycopg.errors.UniqueViolation")).toBeInTheDocument();
    expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/task-runs/1/view");
    expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/task-runs/1/issues/99");
  });
});
