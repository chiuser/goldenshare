import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { wealthFetch } from "./wealthApiClient";
import { saveAuthSession } from "../../features/auth/model/authStorage";
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
