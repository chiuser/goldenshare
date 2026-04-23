import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsV21ReviewIndexPage } from "./ops-v21-review-index-page";

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => {
    if (path.startsWith("/api/v1/ops/review/index/active")) {
      return {
        total: 1,
        items: [
          {
            resource: "index_daily",
            ts_code: "000300.SH",
            index_name: "沪深300",
            first_seen_date: "2026-01-02",
            last_seen_date: "2026-04-17",
            last_checked_at: "2026-04-17T09:10:00+08:00",
          },
        ],
      };
    }
    throw new Error(`unexpected path: ${path}`);
  }),
}));

function renderPage(initialEntry = "/app/ops/v21/review/index") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const rootRoute = createRootRoute({
    component: () => <OpsV21ReviewIndexPage />,
  });
  const route = createRoute({
    getParentRoute: () => rootRoute,
    path: "/ops/v21/review/index",
    component: () => <OpsV21ReviewIndexPage />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([route]),
    basepath: "/app",
    history: createMemoryHistory({ initialEntries: [initialEntry] }),
  });

  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("审查中心指数页", () => {
  it("使用统一页头、筛选栏和表格壳展示激活指数", async () => {
    renderPage();

    expect(await screen.findByText("审查中心 · 指数")).toBeInTheDocument();
    expect(await screen.findByText("筛选与资源池")).toBeInTheDocument();
    expect(await screen.findByLabelText("关键词")).toBeInTheDocument();
    expect(await screen.findByText("激活指数列表")).toBeInTheDocument();
    expect(await screen.findByText("沪深300")).toBeInTheDocument();
  });
});
