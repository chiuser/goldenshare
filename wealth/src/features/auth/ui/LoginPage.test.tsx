import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../../app/App";
import { AuthProvider } from "../model/AuthProvider";
import { LoginPage } from "./LoginPage";

const payload = { token: "access-token", refresh_token: "refresh-token",
  access_token_expires_at: "2026-09-04T16:00:00+08:00", username: "demo", is_admin: false, display_name: "Demo" };
const success = () => new Response(JSON.stringify(payload));
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup() {
  const onAuthenticated = vi.fn();
  const result = render(<AuthProvider><LoginPage redirectPath="/wealth/market/overview?debug=1" onAuthenticated={onAuthenticated} /></AuthProvider>);
  const username = screen.getByLabelText("用户名");
  const password = screen.getByLabelText("密码");
  const form = username.closest("form")!;
  const fill = (u = "demo", p = "secret") => {
    fireEvent.change(username, { target: { value: u } });
    fireEvent.change(password, { target: { value: p } });
  };
  return { ...result, onAuthenticated, username, password, form, fill };
}

describe("LoginPage", () => {
  beforeEach(() => { localStorage.clear(); history.replaceState({}, "", "/wealth/login"); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("U01 renders only the accessible approved brand, two inputs and one submit", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { username, password, container } = setup();
    expect(screen.getByRole("main", { name: "财势天下登录页" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "财势天下" })).toBeInTheDocument();
    expect(container.querySelector(".login-brand__seal img")).toHaveAttribute("alt", "");
    expect(container.querySelectorAll("input")).toHaveLength(2);
    expect(username).toHaveAttribute("autocomplete", "username");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");
    expect(username).not.toHaveAttribute("maxlength");
    expect(password).not.toHaveAttribute("maxlength");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
    expect(screen.queryByText(/Wealth World|注册|数据接入状态|忘记密码/)).not.toBeInTheDocument();
    expect(container.querySelectorAll("label.login-visually-hidden")).toHaveLength(2);
    expect(document.activeElement).not.toBe(username);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([["", "", "用户名"], [" ", "  ", "用户名"], ["", "secret", "用户名"], ["demo", "", "密码"]])(
    "U02 rejects local empty credentials %j / %j and focuses %s", (u, p, first) => {
      const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
      const { fill, form, username, password } = setup(); fill(u, p); fireEvent.submit(form);
      expect(screen.getByLabelText(first)).toHaveFocus();
      expect(screen.getByRole("status")).toHaveTextContent("请输入用户名和密码");
      expect(username.hasAttribute("aria-invalid")).toBe(!u.trim());
      expect(password.hasAttribute("aria-invalid")).toBe(!p.trim());
      expect(fetchMock).not.toHaveBeenCalled();
    });

  it("U03 restarts identical feedback and removes all expired field associations", () => {
    vi.useFakeTimers();
    const { form, username, unmount } = setup();
    fireEvent.submit(form);
    act(() => vi.advanceTimersByTime(2000));
    fireEvent.submit(form);
    act(() => vi.advanceTimersByTime(600));
    expect(screen.getByRole("status")).toHaveTextContent("请输入用户名和密码");
    act(() => vi.advanceTimersByTime(1999));
    expect(screen.getByRole("status")).toHaveTextContent("请输入用户名和密码");
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(username).not.toHaveAttribute("aria-invalid");
    expect(username).not.toHaveAttribute("aria-describedby");
    fireEvent.submit(form); unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([
    ["JSON 401", () => Promise.resolve(new Response(JSON.stringify({ code: "unauthorized", message: "用户名或密码不正确" }), { status: 401 })), "用户名或密码不正确"],
    ["safe 422", () => Promise.resolve(new Response(JSON.stringify({ code: "validation_error", message: "登录参数校验失败，请检查用户名和密码" }), { status: 422 })), "登录参数校验失败，请检查用户名和密码"],
    ["non-JSON 500", () => Promise.resolve(new Response("<html>server failure</html>", { status: 500 })), "请求失败：500"],
    ["network", () => Promise.reject(new Error("Failed to fetch")), "Failed to fetch"],
    ["non-Error", () => Promise.reject({ private: "must not render" }), "登录失败，请检查用户名或密码"],
  ])("U04 exits pending on %s without navigation", async (_, request, message) => {
    vi.stubGlobal("fetch", vi.fn(request));
    const { fill, form, username, password, onAuthenticated } = setup();
    fill(); fireEvent.submit(form);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(message));
    expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
    expect(form).toHaveAttribute("aria-describedby", "login-feedback");
    expect(username).not.toHaveAttribute("aria-invalid");
    expect(username).toHaveValue("demo"); expect(password).toHaveValue("secret");
    expect(onAuthenticated).not.toHaveBeenCalled(); expect(localStorage.length).toBe(0);
  });

  it("U04 keeps long server messages after the button as text, not HTML", async () => {
    const message = "<img src=x onerror=alert(1)>" + "错误".repeat(100);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ message }), { status: 401 })));
    const { fill, form } = setup(); fill(); fireEvent.submit(form);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(message));
    expect(screen.getByRole("status").querySelector("img")).toBeNull();
    expect(form.lastElementChild).toBe(screen.getByRole("status"));
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("U05 locks duplicate submits synchronously, leaves inputs editable, and permits retry", async () => {
    const response = deferred<Response>();
    const fetchMock = vi.fn().mockReturnValueOnce(response.promise).mockResolvedValueOnce(success());
    vi.stubGlobal("fetch", fetchMock);
    const { fill, form, username, onAuthenticated } = setup(); fill();
    act(() => { fireEvent.submit(form); fireEvent.submit(form); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(form).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "登录中…" })).toBeDisabled();
    expect(username).toBeEnabled();
    await act(async () => response.resolve(new Response("bad", { status: 500 })));
    fireEvent.submit(form);
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("U06 trims both request fields, stores the original keys and preserves redirect query", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => success()); vi.stubGlobal("fetch", fetchMock);
    const { fill, form, onAuthenticated } = setup(); fill(" demo ", " secret "); fireEvent.submit(form);
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("/wealth/market/overview?debug=1"));
    expect(JSON.parse(fetchMock.mock.calls[0]![1]!.body as string)).toEqual({ username: "demo", password: "secret" });
    expect(localStorage.getItem("wealth.auth.access-token")).toBe("access-token");
    expect(localStorage.getItem("wealth.auth.refresh-token")).toBe("refresh-token");
    expect(localStorage.getItem("wealth.auth.expires-at")).toBe(payload.access_token_expires_at);
    expect(localStorage.getItem("wealth.auth.username")).toBe("demo");
    expect(localStorage.getItem("wealth.auth.display-name")).toBe("Demo");
    expect(localStorage.length).toBe(5);
  });

  it("U06 redirects unauthenticated protected visits without making an auth request", async () => {
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    history.replaceState({}, "", "/wealth/market/overview?debug=1"); render(<App />);
    expect(screen.getByLabelText("财势天下登录页")).toBeInTheDocument();
    await waitFor(() => expect(location.pathname).toBe("/wealth/login"));
    expect(new URLSearchParams(location.search).get("redirect")).toBe("/wealth/market/overview?debug=1");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["resolve", "reject"] as const)("U11 times out at 10000ms; late %s cannot pollute a new attempt", async (late) => {
    vi.useFakeTimers();
    const first = deferred<Response>(); const second = deferred<Response>();
    const fetchMock = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    vi.stubGlobal("fetch", fetchMock);
    const { fill, form, onAuthenticated } = setup(); fill(); fireEvent.submit(form);
    await act(async () => vi.advanceTimersByTimeAsync(9999));
    expect(screen.getByRole("button", { name: "登录中…" })).toBeDisabled();
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(screen.getByRole("status")).toHaveTextContent("登录超时，请重试");
    expect(fetchMock.mock.calls[0]![1].signal.aborted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(2599));
    expect(screen.getByRole("status")).toHaveTextContent("登录超时，请重试");
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    fireEvent.submit(form);
    await act(async () => { if (late === "resolve") first.resolve(success()); else first.reject(new Error("late")); });
    expect(localStorage.length).toBe(0); expect(onAuthenticated).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "登录中…" })).toBeDisabled();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    await act(async () => second.resolve(success()));
    expect(onAuthenticated).toHaveBeenCalledOnce();
    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(vi.getTimerCount()).toBe(0);
  });

  it("U11 aborts on unmount and ignores a successful response from an abort-ignoring transport", async () => {
    const response = deferred<Response>(); const fetchMock = vi.fn<typeof fetch>(() => response.promise);
    vi.stubGlobal("fetch", fetchMock);
    const { fill, form, unmount, onAuthenticated } = setup(); fill(); fireEvent.submit(form); unmount();
    expect(fetchMock.mock.calls[0]![1]!.signal!.aborted).toBe(true);
    await act(async () => response.resolve(success()));
    expect(localStorage.length).toBe(0); expect(onAuthenticated).not.toHaveBeenCalled();
  });
});
