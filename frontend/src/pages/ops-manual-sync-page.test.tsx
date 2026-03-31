import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryHistory } from "@tanstack/react-router";
import { RouterProvider, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { OpsManualSyncPage } from "./ops-manual-sync-page";


vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => {
    if (path === "/api/v1/ops/catalog") {
      return {
        job_specs: [
          {
            key: "sync_history.stock_basic",
            display_name: "股票基础信息",
            category: "sync_history",
            description: "刷新股票基础资料。",
            strategy_type: "resource",
            executor_kind: "sync_service",
            target_tables: ["core.security"],
            supports_manual_run: true,
            supports_schedule: true,
            supports_retry: true,
            schedule_binding_count: 0,
            active_schedule_count: 0,
            supported_params: [
              {
                key: "exchange",
                display_name: "交易所",
                param_type: "enum",
                description: "按交易所筛选。",
                required: false,
                multi_value: false,
              },
            ],
          },
        ],
        workflow_specs: [],
      };
    }
    throw new Error(`unexpected path: ${path}`);
  }),
}));

function renderPage() {
  window.history.replaceState({}, "", "/app/ops/manual-sync?spec_key=sync_history.stock_basic&spec_type=job");
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const rootRoute = createRootRoute({
    component: () => <OpsManualSyncPage />,
  });
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/ops/manual-sync",
    component: () => <OpsManualSyncPage />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
    basepath: "/app",
    history: createMemoryHistory({ initialEntries: ["/app/ops/manual-sync?spec_key=sync_history.stock_basic&spec_type=job"] }),
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

describe("手动同步页", () => {
  it("在参数选项缺失时仍能正常渲染", async () => {
    renderPage();

    expect(await screen.findByText("手动同步")).toBeInTheDocument();
    expect(await screen.findByText("开始同步")).toBeInTheDocument();
  });
});
