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
});
