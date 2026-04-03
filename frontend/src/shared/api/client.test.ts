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
    const replaceSpy = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      pathname: "/app/ops/data-status",
      replace: replaceSpy,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ code: "unauthorized", message: "Token has expired" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })),
    );

    await expect(apiRequest("/api/v1/auth/me")).rejects.toBeInstanceOf(ApiError);

    expect(window.localStorage.getItem("goldenshare.frontend.auth.token")).toBeNull();
    expect(replaceSpy).toHaveBeenCalledWith("/app/login");
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
