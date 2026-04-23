import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { OpsTasksPage } from "./ops-v21-task-records-tab";

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

  it("任务列表会隐藏结果摘要列，给主要信息留出空间", async () => {
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
    expect(screen.queryByText("结果摘要")).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "查看详情" })).toBeInTheDocument();
    expect((await screen.findAllByText("手动")).length).toBeGreaterThan(0);
  });

  it("移除顶部冗余说明后，将筛选栏并入任务记录板块并默认显示全选", async () => {
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
    expect(screen.queryByText("在这里看最近跑了什么、结果怎么样，再决定是查看详情、停止处理，还是重新提交。")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "查看数据状态" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "去手动同步" })).not.toBeInTheDocument();
    expect(screen.queryByText("筛选任务")).not.toBeInTheDocument();

    const taskRecordsCard = screen.getByText("任务记录").closest(".mantine-Paper-root");
    expect(taskRecordsCard).not.toBeNull();

    const statusFilter = within(taskRecordsCard as HTMLElement).getByRole("textbox", { name: "当前状态" });
    const triggerFilter = within(taskRecordsCard as HTMLElement).getByRole("textbox", { name: "发起方式" });
    const specFilter = within(taskRecordsCard as HTMLElement).getByRole("textbox", { name: "任务名称" });

    expect(statusFilter).toHaveValue("全选");
    expect(triggerFilter).toHaveValue("全选");
    expect(specFilter).toHaveValue("全选");
  });
});
