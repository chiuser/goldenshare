import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { PlatformCheckPage } from "./platform-check-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

const { useCurrentUser } = vi.hoisted(() => ({
  useCurrentUser: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
}));

vi.mock("../features/auth/auth-context", () => ({
  useCurrentUser,
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <PlatformCheckPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("平台检查页", () => {
  it("展示统一页头、健康状态和当前用户信息", async () => {
    apiRequest.mockResolvedValueOnce({
      status: "ok",
      service: "goldenshare-web",
      env: "local",
    });
    useCurrentUser.mockReturnValue({
      data: {
        username: "admin",
        display_name: "管理员",
      },
    });

    renderPage();

    expect(await screen.findByText("平台检查")).toBeInTheDocument();
    expect(await screen.findAllByText("服务正常")).toHaveLength(2);
    expect(await screen.findByText("当前状态")).toBeInTheDocument();
    expect(await screen.findByText("管理员")).toBeInTheDocument();
  });
});
