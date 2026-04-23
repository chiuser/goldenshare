import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsV21AccountPage } from "./ops-v21-account-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
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
        <OpsV21AccountPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("帐号管理", () => {
  beforeEach(() => {
    apiRequest.mockReset();
    apiRequest.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/admin/users?")) {
        return { total: 0, items: [] };
      }
      if (path.startsWith("/api/v1/admin/invites?")) {
        return { total: 0, items: [] };
      }
      throw new Error(`unexpected api path: ${path}`);
    });
  });

  it("新建账号用户名输入不会触发事件空指针", async () => {
    renderPage();

    expect(await screen.findByText("新建账号")).toBeInTheDocument();
    const usernameInput = screen.getByLabelText("用户名");

    fireEvent.change(usernameInput, { target: { value: "new_user" } });

    expect((usernameInput as HTMLInputElement).value).toBe("new_user");
  });

  it("用户列表使用统一状态标签，并通过抽屉承接编辑动作", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/admin/users?")) {
        return {
          total: 1,
          items: [
            {
              id: 1,
              username: "operator_01",
              display_name: "运营同学",
              email: "ops@example.com",
              is_admin: false,
              is_active: true,
              account_state: "pending_verification",
              roles: ["operator"],
              last_login_at: "2026-04-23T10:00:00+08:00",
            },
          ],
        };
      }
      if (path.startsWith("/api/v1/admin/invites?")) {
        return { total: 0, items: [] };
      }
      throw new Error(`unexpected api path: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("共 1 个账号")).toBeInTheDocument();
    expect(await screen.findByText("运营同学")).toBeInTheDocument();
    expect((await screen.findAllByText("启用")).length).toBeGreaterThan(0);
    expect(await screen.findByText("待验证")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));

    expect(await screen.findByText("编辑账号 · operator_01")).toBeInTheDocument();
    const displayNameInputs = await screen.findAllByLabelText("显示名称");
    expect(displayNameInputs.some((input) => (input as HTMLInputElement).value === "运营同学")).toBe(true);
  });
});
