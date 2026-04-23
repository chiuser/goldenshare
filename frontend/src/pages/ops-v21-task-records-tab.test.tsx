import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import type { ExecutionListResponse, ExecutionSummaryResponse } from "../shared/api/types";
import { OpsTasksPage } from "./ops-v21-task-records-tab";

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

function createExecutionItem(id: number, overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id,
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
    ...overrides,
  };
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function renderTaskRecordsPage(initialEntry = "/app/ops/tasks") {
  const queryClient = createQueryClient();
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
    history: createMemoryHistory({ initialEntries: [initialEntry] }),
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

beforeEach(() => {
  vi.mocked(apiRequest).mockClear();
  vi.mocked(apiRequest).mockImplementation(async (path: string) => {
    const url = new URL(path, "https://example.test");
    if (url.pathname === "/api/v1/ops/catalog") {
      return {
        job_specs: [
          {
            key: "backfill_equity_series.daily",
            display_name: "股票日线维护",
          },
        ],
        workflow_specs: [],
      };
    }
    if (url.pathname === "/api/v1/ops/executions/summary") {
      return {
        total: 41,
        queued: 3,
        running: 4,
        success: 28,
        failed: 5,
        canceled: 1,
      };
    }
    if (url.pathname === "/api/v1/ops/executions") {
      return {
        total: 41,
        items: [
          createExecutionItem(1),
        ],
      };
    }
    throw new Error(`unexpected path: ${path}`);
  });
});

describe("任务记录页", () => {
  it("从默认入口进入时，会显示当前筛选任务统计并把第一页写入 URL", async () => {
    window.history.replaceState({}, "", "/app/ops/tasks");

    renderTaskRecordsPage("/app/ops/tasks");

    expect(await screen.findByText("任务统计")).toBeInTheDocument();
    expect(screen.getByText("当前筛选任务")).toBeInTheDocument();

    const statCard = screen.getByText("当前筛选任务").closest(".mantine-Paper-root");
    expect(statCard).not.toBeNull();
    await waitFor(() => {
      expect(within(statCard as HTMLElement).getByRole("heading", { level: 3, name: "41" })).toBeInTheDocument();
      expect(window.location.search).toBe("?page=1");
    });
  });

  it("任务列表会隐藏结果摘要列，给主要信息留出空间", async () => {
    renderTaskRecordsPage();

    expect(await screen.findByText("任务记录")).toBeInTheDocument();
    expect(screen.queryByText("结果摘要")).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "查看详情" })).toBeInTheDocument();
    expect((await screen.findAllByText("手动")).length).toBeGreaterThan(0);
  });

  it("移除顶部冗余说明后，将筛选栏并入任务记录板块并默认显示全选", async () => {
    renderTaskRecordsPage();

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

  it("列表数据准备好后，不再等待 catalog 请求才能显示任务记录", async () => {
    const catalogPromise = new Promise<never>(() => undefined);
    vi.mocked(apiRequest).mockImplementation(async (path: string) => {
      const url = new URL(path, "https://example.test");
      if (url.pathname === "/api/v1/ops/catalog") {
        return catalogPromise;
      }
      if (url.pathname === "/api/v1/ops/executions/summary") {
        return {
          total: 1,
          queued: 0,
          running: 1,
          success: 0,
          failed: 0,
          canceled: 0,
        };
      }
      if (url.pathname === "/api/v1/ops/executions") {
        return {
          total: 1,
          items: [
            createExecutionItem(1),
          ],
        };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderTaskRecordsPage();

    expect(await screen.findByRole("link", { name: "查看详情" })).toBeInTheDocument();
    expect(screen.queryByLabelText("表格加载中")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "任务名称" })).toHaveValue("全选");
  });

  it("按页请求任务列表，并在清空筛选时回到第一页", async () => {
    window.history.replaceState({}, "", "/app/ops/tasks?status=failed&page=2");

    renderTaskRecordsPage("/app/ops/tasks?status=failed&page=2");

    expect(await screen.findByText("任务统计")).toBeInTheDocument();
    await waitFor(() => {
      expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path === "/api/v1/ops/executions/summary?status=failed")).toBe(true);
      expect(
        vi.mocked(apiRequest).mock.calls.some(([path]) => path === "/api/v1/ops/executions?status=failed&page=2&limit=20&offset=20"),
      ).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));

    await waitFor(() => {
      expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path === "/api/v1/ops/executions?page=1&limit=20&offset=0")).toBe(true);
      expect(window.location.search).toBe("?page=1");
    });
  });

  it("第一次切换到未缓存筛选项时，保留上一份列表并显示刷新提示", async () => {
    Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    let resolveFilteredExecutions!: (value: ExecutionListResponse) => void;
    let resolveFilteredSummary!: (value: ExecutionSummaryResponse) => void;
    vi.mocked(apiRequest).mockImplementation((path: string) => {
      const url = new URL(path, "https://example.test");
      if (url.pathname === "/api/v1/ops/catalog") {
        return Promise.resolve({
          job_specs: [
            {
              key: "backfill_equity_series.daily",
              display_name: "股票日线维护",
            },
          ],
          workflow_specs: [],
        });
      }
      if (path === "/api/v1/ops/executions/summary") {
        return Promise.resolve({
          total: 41,
          queued: 3,
          running: 4,
          success: 28,
          failed: 5,
          canceled: 1,
        });
      }
      if (path === "/api/v1/ops/executions?page=1&limit=20&offset=0") {
        return Promise.resolve({
          total: 41,
          items: [createExecutionItem(1, { spec_display_name: "股票日线维护" })],
        });
      }
      if (path === "/api/v1/ops/executions/summary?status=failed") {
        return new Promise<ExecutionSummaryResponse>((resolve) => {
          resolveFilteredSummary = resolve;
        });
      }
      if (path === "/api/v1/ops/executions?status=failed&page=1&limit=20&offset=0") {
        return new Promise<ExecutionListResponse>((resolve) => {
          resolveFilteredExecutions = resolve;
        });
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const user = userEvent.setup();
    renderTaskRecordsPage();

    expect(await screen.findByRole("link", { name: "查看详情" })).toBeInTheDocument();

    await user.click(screen.getByRole("textbox", { name: "当前状态" }));
    await user.click(await screen.findByRole("option", { name: "执行失败", hidden: true }));

    expect(screen.getByRole("link", { name: "查看详情" })).toBeInTheDocument();
    expect(screen.getByText("正在刷新...")).toBeInTheDocument();
    expect(screen.queryByLabelText("表格加载中")).not.toBeInTheDocument();

    resolveFilteredSummary({
      total: 0,
      queued: 0,
      running: 0,
      success: 0,
      failed: 0,
      canceled: 0,
    });
    resolveFilteredExecutions({
      total: 0,
      items: [],
    });

    await waitFor(() => {
      expect(screen.getByText("当前筛选下没有任务记录")).toBeInTheDocument();
      expect(screen.queryByText("正在刷新...")).not.toBeInTheDocument();
    });
  });
});
