import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthApiError, login, logout, refreshToken } from "./authApi";

const payload = { token: "access", refresh_token: "refresh", username: "demo", is_admin: false, display_name: null };
describe("authApi unchanged HTTP contract — U08", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
  it.each([true, false])("preserves login/refresh URLs, JSON fields and optional signal (signal=%s)", async (withSignal) => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify(payload)));
    vi.stubGlobal("fetch", fetchMock);
    const signal = withSignal ? new AbortController().signal : undefined;
    expect(await login({ username: "demo", password: "secret" }, signal)).toEqual(payload);
    expect(await refreshToken({ refresh_token: "refresh" }, signal)).toEqual(payload);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/auth/login", { method: "POST", signal,
      headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ username: "demo", password: "secret" }) });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v1/auth/refresh", { method: "POST", signal,
      headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: "refresh" }) });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it.each(["access", null])("keeps logout JSON, optional bearer and signal (%s)", async (accessToken) => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock); const signal = new AbortController().signal;
    await logout({ refresh_token: "refresh" }, accessToken, signal);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/v1/auth/logout"); expect(init?.method).toBe("POST"); expect(init?.signal).toBe(signal);
    expect(init?.body).toBe(JSON.stringify({ refresh_token: "refresh" }));
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe(accessToken ? "Bearer access" : null);
    expect(headers.get("Content-Type")).toBe("application/json"); expect(headers.get("Accept")).toBe("application/json");
  });
  it.each([
    [401, JSON.stringify({ code: "unauthorized", message: "用户名或密码不正确" }), "unauthorized", "用户名或密码不正确"],
    [422, JSON.stringify({ code: "validation_error", message: "登录参数校验失败，请检查用户名和密码" }), "validation_error", "登录参数校验失败，请检查用户名和密码"],
    [500, "<html>failure</html>", "HTTP_500", "请求失败：500"],
    [403, "{}", "HTTP_403", "请求失败：403"],
  ])("keeps original code/message/fallback for HTTP %i", async (status, responseBody, code, message) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(responseBody, { status })));
    const error = await login({ username: "demo", password: "secret" }).catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(AuthApiError); expect(error).toMatchObject({ status, code, message });
  });
  it("passes through a network failure unchanged", async () => {
    const error = new Error("network unavailable"); vi.stubGlobal("fetch", vi.fn().mockRejectedValue(error));
    await expect(login({ username: "demo", password: "secret" })).rejects.toBe(error);
  });
});
