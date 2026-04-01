import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { OpsTasksPage } from "./ops-tasks-page";

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => {
    if (path === "/api/v1/ops/catalog") {
      return {
        job_specs: [],
        workflow_specs: [],
      };
    }
    if (path === "/api/v1/ops/executions") {
      return {
        total: 1,
        items: [
          {
            id: 1,
            spec_type: "job",
            spec_key: "backfill_equity_series.daily",
            spec_display_name: "股票日线维护",
            schedule_display_name: null,
            trigger_source: "manual",
            status: "running",
            requested_by_username: "admin",
            requested_at: "2026-03-31T01:00:00Z",
            started_at: "2026-03-31T01:00:02Z",
            ended_at: null,
            rows_fetched: 0,
            rows_written: 0,
            progress_current: 651,
            progress_total: 5814,
            progress_percent: 11,
            progress_message: "daily: 651/5814 ts_code=002034.SZ fetched=6 written=6",
            last_progress_at: "2026-03-31T01:00:05Z",
            summary_message: "正在汇总",
            error_code: null,
          },
        ],
      };
    }
    throw new Error(`unexpected path: ${path}`);
  }),
}));

describe("任务记录页", () => {
  it("从默认入口进入时，不应该带上历史筛选条件", async () => {
    window.history.replaceState({}, "", "/app/ops/tasks");
    window.localStorage.setItem(
      "goldenshare.frontend.ops.tasks.filters",
      JSON.stringify({ status: "failed", trigger_source: null, spec_key: null }),
    );

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });

    const rootRoute = createRootRoute({
      component: () => <OpsTasksPage />,
    });
    const route = createRoute({
      getParentRoute: () => rootRoute,
      path: "/ops/tasks",
      component: () => <OpsTasksPage />,
    });
    const router = createRouter({
      routeTree: rootRoute.addChildren([route]),
      basepath: "/app",
      history: createMemoryHistory({ initialEntries: ["/app/ops/tasks"] }),
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

    expect(await screen.findByText("任务记录")).toBeInTheDocument();
    const statCard = (await screen.findByText("当前结果集")).closest(".mantine-Paper-root");
    expect(statCard).not.toBeNull();
    expect(within(statCard as HTMLElement).getByRole("heading", { level: 3, name: "1" })).toBeInTheDocument();
  });

  it("有结构化进度时，优先展示当前进展而不是旧的汇总文案", async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });

    const rootRoute = createRootRoute({
      component: () => <OpsTasksPage />,
    });
    const route = createRoute({
      getParentRoute: () => rootRoute,
      path: "/ops/tasks",
      component: () => <OpsTasksPage />,
    });
    const router = createRouter({
      routeTree: rootRoute.addChildren([route]),
      basepath: "/app",
      history: createMemoryHistory({ initialEntries: ["/app/ops/tasks"] }),
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

    expect(await screen.findByText("任务记录")).toBeInTheDocument();
    expect(await screen.findByText("当前进展 651/5814（11%）")).toBeInTheDocument();
    expect(screen.queryByText("正在汇总")).not.toBeInTheDocument();
  });
});
