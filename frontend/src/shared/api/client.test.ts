import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "./client";
import { ApiError } from "./errors";


describe("apiRequest unauthorized handling", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("clears token and redirects to login when token is expired on authenticated pages", async () => {
    window.localStorage.setItem("goldenshare.frontend.auth.token", "expired-token");
    window.localStorage.setItem("goldenshare.frontend.auth.refresh-token", "expired-refresh-token");
    const replaceSpy = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      pathname: "/app/ops/data-status",
      replace: replaceSpy,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ code: "unauthorized", message: "Token has expired" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
          }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ code: "unauthorized", message: "Refresh token is invalid" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
          }),
        ),
    );

    await expect(apiRequest("/api/v1/auth/me")).rejects.toBeInstanceOf(ApiError);

    expect(window.localStorage.getItem("goldenshare.frontend.auth.token")).toBeNull();
    expect(window.localStorage.getItem("goldenshare.frontend.auth.refresh-token")).toBeNull();
    expect(replaceSpy).toHaveBeenCalledWith("/app/login");
  });

  it("refreshes token and retries once when access token expires", async () => {
    window.localStorage.setItem("goldenshare.frontend.auth.token", "expired-token");
    window.localStorage.setItem("goldenshare.frontend.auth.refresh-token", "valid-refresh-token");
    vi.stubGlobal("location", {
      ...window.location,
      pathname: "/app/ops/data-status",
      replace: vi.fn(),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ code: "unauthorized", message: "Token has expired" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
          }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ token: "new-access-token", refresh_token: "new-refresh-token" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
    );

    const payload = await apiRequest<{ ok: boolean }>("/api/v1/auth/me");

    expect(payload.ok).toBe(true);
    expect(window.localStorage.getItem("goldenshare.frontend.auth.token")).toBe("new-access-token");
    expect(window.localStorage.getItem("goldenshare.frontend.auth.refresh-token")).toBe("new-refresh-token");
  });

  it("does not redirect on login failure", async () => {
    const replaceSpy = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      pathname: "/app/login",
      replace: replaceSpy,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ code: "unauthorized", message: "Username or password is incorrect" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })),
    );

    await expect(
      apiRequest("/api/v1/auth/login", {
        method: "POST",
        body: { username: "admin", password: "wrong" },
      }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(replaceSpy).not.toHaveBeenCalled();
  });
});
