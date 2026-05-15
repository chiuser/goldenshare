import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../../app/App";
import { AuthProvider } from "../model/AuthProvider";
import { LoginPage } from "./LoginPage";

function authSuccessResponse() {
  return new Response(
    JSON.stringify({
      token: "access-token",
      refresh_token: "refresh-token",
      access_token_expires_at: "2026-05-14T16:00:00+08:00",
      username: "demo",
      is_admin: false,
      display_name: "Demo",
    }),
    {
      status: 200,
      headers: { "Content-Type": "application/json" },
    },
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.pushState({}, "", "/wealth/login");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the showcase register button visual but does not call backend registration", () => {
    const onAuthenticated = vi.fn();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AuthProvider>
        <LoginPage redirectPath="/wealth/market/overview" onAuthenticated={onAuthenticated} />
      </AuthProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "注册" }));

    expect(screen.getByText("注册入口暂未开放")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  it("blocks empty credentials before sending login request", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AuthProvider>
        <LoginPage redirectPath="/wealth/market/overview" onAuthenticated={vi.fn()} />
      </AuthProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(screen.getByText("请输入用户名和密码")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("saves wealth auth tokens and returns to the protected page after login succeeds", async () => {
    const onAuthenticated = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => authSuccessResponse()));

    render(
      <AuthProvider>
        <LoginPage redirectPath="/wealth/market/overview?debug=1" onAuthenticated={onAuthenticated} />
      </AuthProvider>,
    );

    fireEvent.change(screen.getByPlaceholderText("请输入用户名"), { target: { value: "demo" } });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("/wealth/market/overview?debug=1"));
    expect(window.localStorage.getItem("wealth.auth.access-token")).toBe("access-token");
    expect(window.localStorage.getItem("wealth.auth.refresh-token")).toBe("refresh-token");
  });

  it("routes unauthenticated market overview visits to the wealth login page", async () => {
    window.history.pushState({}, "", "/wealth/market/overview");

    render(<App />);

    expect(screen.getByLabelText("财势乾坤行情系统登录页")).toBeInTheDocument();
    expect(screen.getByLabelText("登录表单")).toBeInTheDocument();
    expect(screen.queryByText("QUOTE TERMINAL")).not.toBeInTheDocument();
    expect(screen.queryByText("行情系统登录")).not.toBeInTheDocument();
    expect(screen.queryByText("专业 · 稳定 · 高密度行情终端")).not.toBeInTheDocument();
    await waitFor(() => expect(window.location.pathname).toBe("/wealth/login"));
    expect(new URLSearchParams(window.location.search).get("redirect")).toBe("/wealth/market/overview");
  });
});
