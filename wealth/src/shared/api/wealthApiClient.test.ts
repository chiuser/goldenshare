import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { wealthFetch } from "./wealthApiClient";
import { clearAuthSession, readAuthSession, saveAuthSession } from "../../features/auth/model/authStorage";
import { WEALTH_AUTH_REQUIRED_EVENT } from "../../features/auth/model/authEvents";

const fresh = { token: "new-access", refresh_token: "new-refresh", username: "demo", is_admin: false };
describe("wealthFetch unchanged refresh contract — U09", () => {
  beforeEach(() => { localStorage.clear(); saveAuthSession({ ...fresh, token: "old-access", refresh_token: "old-refresh" }); });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
  it.each([200, 403, 500])("makes exactly one bearer request for non-401 status %i", async (status) => {
    const response = new Response("result", { status }); const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
    vi.stubGlobal("fetch", fetchMock); const dispatch = vi.spyOn(window, "dispatchEvent");
    expect(await wealthFetch("/api/resource", { headers: { "X-Request": "value" } })).toBe(response);
    expect(fetchMock).toHaveBeenCalledOnce();
    const headers = new Headers(fetchMock.mock.calls[0]![1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer old-access"); expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("X-Request")).toBe("value"); expect(dispatch).not.toHaveBeenCalled();
  });
  it("refreshes once and replays the original request once with the new token", async () => {
    const replay = new Response("success");
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response("expired", { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(fresh))).mockResolvedValueOnce(replay);
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;
    expect(await wealthFetch("/api/resource?q=1", { method: "POST", body: "body", signal })).toBe(replay);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]![0]).toBe("/api/v1/auth/refresh");
    expect(JSON.parse(fetchMock.mock.calls[1]![1]!.body as string)).toEqual({ refresh_token: "old-refresh" });
    expect(fetchMock.mock.calls[2]![0]).toBe("/api/resource?q=1");
    expect(fetchMock.mock.calls[2]![1]).toMatchObject({ method: "POST", body: "body", signal });
    expect(new Headers(fetchMock.mock.calls[2]![1]?.headers).get("Authorization")).toBe("Bearer new-access");
    expect(localStorage.getItem("wealth.auth.refresh-token")).toBe("new-refresh");
  });
  it("never replays a trading-assistant write after successful refresh", async () => {
    const first = new Response("expired", { status: 401 });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(first)
      .mockResolvedValueOnce(new Response(JSON.stringify(fresh)));
    vi.stubGlobal("fetch", fetchMock);
    expect(await wealthFetch("/api/write", { method: "POST", body: "original" }, { replayAfterRefresh: false })).toBe(first);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0]![1]).not.toHaveProperty("replayAfterRefresh");
    expect(readAuthSession()?.accessToken).toBe("new-access");
  });
  it("does not log out when the caller cancels token refresh", async () => {
    const controller = new AbortController();
    const first = new Response("expired", { status: 401 });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(first)
      .mockImplementationOnce(async () => { controller.abort(); throw new DOMException("Aborted", "AbortError"); });
    vi.stubGlobal("fetch", fetchMock);
    expect(await wealthFetch("/api/write", { method: "POST", signal: controller.signal }, { replayAfterRefresh: false })).toBe(first);
    expect(readAuthSession()?.accessToken).toBe("old-access");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it("a late replay 401 cannot clear credentials refreshed by another request", async () => {
    let finish!: (response: Response) => void;
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response("expired", { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(fresh)))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { finish = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const result = wealthFetch("/api/read");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    saveAuthSession({ ...fresh, token: "newest-access", refresh_token: "newest-refresh" }, "refresh");
    const denied = new Response("late", { status: 401 }); finish(denied);
    expect(await result).toBe(denied);
    expect(readAuthSession()?.accessToken).toBe("newest-access");
  });
  it.each(["logout", "other-user"])("drops a late refresh after %s without overwriting or clearing that session", async (action) => {
    let finish!: (response: Response) => void;
    const refresh = new Promise<Response>((resolve) => { finish = resolve; });
    const first = new Response("expired", { status: 401 });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(first).mockReturnValueOnce(refresh);
    vi.stubGlobal("fetch", fetchMock);
    const result = wealthFetch("/api/write", { method: "POST" }, { replayAfterRefresh: false });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    if (action === "logout") clearAuthSession();
    else saveAuthSession({ ...fresh, token: "other-access", refresh_token: "other-refresh", username: "other" });
    const expected = readAuthSession();
    finish(new Response(JSON.stringify(fresh)));
    expect(await result).toBe(first);
    expect(readAuthSession()).toEqual(expected);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it("does not refresh an old request using a newly logged-in user's credentials", async () => {
    let finish!: (response: Response) => void;
    const fetchMock = vi.fn<typeof fetch>().mockReturnValue(new Promise<Response>((resolve) => { finish = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const pending = wealthFetch("/api/write", { method: "POST" });
    saveAuthSession({ ...fresh, username: "other", token: "other-access" });
    const first = new Response("expired", { status: 401 }); finish(first);
    expect(await pending).toBe(first);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(readAuthSession()?.username).toBe("other");
  });
  it.each(["missing-refresh", "refresh-rejected", "refresh-network", "replay-401"])("terminates and clears auth on %s", async (scenario) => {
    if (scenario === "missing-refresh") localStorage.removeItem("wealth.auth.refresh-token");
    const first = new Response("expired", { status: 401 }); const replay = new Response("still expired", { status: 401 });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(first);
    if (scenario === "refresh-rejected") fetchMock.mockResolvedValueOnce(new Response("denied", { status: 401 }));
    if (scenario === "refresh-network") fetchMock.mockRejectedValueOnce(new Error("offline"));
    if (scenario === "replay-401") fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(fresh))).mockResolvedValueOnce(replay);
    vi.stubGlobal("fetch", fetchMock); const dispatch = vi.spyOn(window, "dispatchEvent");
    expect(await wealthFetch("/api/resource")).toBe(scenario === "replay-401" ? replay : first);
    expect(fetchMock).toHaveBeenCalledTimes(scenario === "missing-refresh" ? 1 : scenario === "replay-401" ? 3 : 2);
    expect(localStorage.length).toBe(0); expect(dispatch).toHaveBeenCalledOnce();
    expect(dispatch.mock.calls[0]![0].type).toBe(WEALTH_AUTH_REQUIRED_EVENT);
  });
});
