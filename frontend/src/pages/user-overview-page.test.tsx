import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { UserOverviewPage } from "./user-overview-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

const { clearToken } = vi.hoisted(() => ({
  clearToken: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
}));

vi.mock("../features/auth/auth-context", () => ({
  useAuth: () => ({
    clearToken,
  }),
}));

vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    useNavigate: () => vi.fn(),
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
        <UserOverviewPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("用户状态概览页", () => {
  it("使用统一页头和统计卡展示 freshness 汇总", async () => {
    apiRequest.mockResolvedValueOnce({
      freshness_summary: {
        total_datasets: 12,
        fresh_datasets: 9,
        lagging_datasets: 2,
        stale_datasets: 1,
        unknown_datasets: 0,
        disabled_datasets: 1,
      },
    });

    renderPage();

    expect(await screen.findByText("状态概览")).toBeInTheDocument();
    expect(await screen.findByText("数据状态总览")).toBeInTheDocument();
    expect(await screen.findByText("数据集总数")).toBeInTheDocument();
    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出登录" })).toBeInTheDocument();
  });
});
