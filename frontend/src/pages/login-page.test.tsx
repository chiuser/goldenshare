import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { LoginPage } from "./login-page";


vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});


describe("LoginPage", () => {
  it("renders login form", () => {
    const queryClient = new QueryClient();
    render(
      <MantineProvider theme={appTheme}>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <LoginPage />
          </AuthProvider>
        </QueryClientProvider>
      </MantineProvider>,
    );

    expect(screen.getByText("登录前端应用")).toBeInTheDocument();
    expect(screen.getByLabelText("用户名")).toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "进入应用" })).toBeInTheDocument();
  });
});
