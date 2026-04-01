import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { OpsTaskDetailPage } from "./ops-task-detail-page";

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => {
    if (path === "/api/v1/ops/executions/1") {
      return {
        id: 1,
        schedule_id: null,
        spec_type: "job",
        spec_key: "backfill_equity_series.daily",
        spec_display_name: "股票日线维护",
        schedule_display_name: null,
        trigger_source: "manual",
        status: "running",
        requested_by_username: "admin",
        requested_at: "2026-03-31T01:00:00Z",
        queued_at: "2026-03-31T01:00:01Z",
        started_at: "2026-03-31T01:00:02Z",
        ended_at: null,
        params_json: {
          start_date: "2026-03-23",
          end_date: "2026-03-30",
        },
        summary_message: null,
        rows_fetched: 0,
        rows_written: 0,
        progress_current: 651,
        progress_total: 5814,
        progress_percent: 11,
        progress_message: "daily: 651/5814 ts_code=002034.SZ fetched=6 written=6",
        last_progress_at: "2026-03-31T01:00:05Z",
        cancel_requested_at: null,
        canceled_at: null,
        error_code: null,
        error_message: null,
      };
    }
    if (path === "/api/v1/ops/executions/1/steps") {
      return {
        execution_id: 1,
        items: [
          {
            id: 10,
            step_key: "backfill_equity_series.daily",
            display_name: "股票日线维护",
            sequence_no: 1,
            unit_kind: null,
            unit_value: null,
            status: "running",
            started_at: "2026-03-31T01:00:02Z",
            ended_at: null,
            rows_fetched: 0,
            rows_written: 0,
            message: null,
          },
        ],
      };
    }
    if (path === "/api/v1/ops/executions/1/events") {
      return {
        execution_id: 1,
        items: [
          {
            id: 100,
            step_id: 10,
            event_type: "step_progress",
            level: "info",
            message: "正在拉取 2026-03-23 到 2026-03-30 的股票日线数据",
            payload_json: {},
            occurred_at: "2026-03-31T01:00:05Z",
          },
        ],
      };
    }
    if (path === "/api/v1/ops/executions/1/logs") {
      return {
        execution_id: 1,
        items: [],
      };
    }
    throw new Error(`unexpected path: ${path}`);
  }),
}));

describe("任务详情页", () => {
  it("默认先展示状态、范围和下一步建议，把技术细节后置", async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });

    const rootRoute = createRootRoute({
      component: () => <OpsTaskDetailPage executionId={1} />,
    });
    const route = createRoute({
      getParentRoute: () => rootRoute,
      path: "/ops/tasks/$executionId",
      component: () => <OpsTaskDetailPage executionId={1} />,
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

    expect(await screen.findByText("任务详情")).toBeInTheDocument();
    expect(await screen.findByText("本次处理范围")).toBeInTheDocument();
    expect((await screen.findAllByText("当前进展")).length).toBeGreaterThan(0);
    expect(await screen.findByText("建议下一步")).toBeInTheDocument();
    expect(await screen.findByText("查看技术细节")).toBeInTheDocument();
    expect(await screen.findByText("651/5814（11%）")).toBeInTheDocument();
    expect((await screen.findAllByText("正在拉取 2026-03-23 到 2026-03-30 的股票日线数据")).length).toBeGreaterThan(0);
  });
});
