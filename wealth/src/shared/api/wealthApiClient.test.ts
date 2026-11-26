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

const etfActivityPath = "/api/v1/wealth/market/etf-activity";
const majorEtfMonitorPath = "/api/v1/wealth/market/major-etf-monitor";
const refreshPath = "/api/v1/auth/refresh";
const old = { ...fresh, token: "old-access", refresh_token: "old-refresh" };

function controlledFetch() {
  const calls: Array<{
    url: string;
    init?: RequestInit;
    respond: (response: Response) => void;
    fail: (reason: Error) => void;
  }> = [];
  vi.stubGlobal("fetch", vi.fn<typeof fetch>((url, init) => new Promise<Response>((respond, fail) => {
    calls.push({ url: String(url), init, respond, fail });
  })));
  return calls;
}

function authorization(call: ReturnType<typeof controlledFetch>[number]) {
  return new Headers(call.init?.headers).get("Authorization");
}

function expired() {
  return new Response("expired", { status: 401 });
}

function nextTask() {
  return new Promise<void>((resolve) => setTimeout(resolve, 0));
}

describe("wealthFetch concurrent renewal", () => {
  beforeEach(() => {
    localStorage.clear();
    saveAuthSession(old);
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("sends each valid ETF request once without a renewal", async () => {
    const calls = controlledFetch();
    const pending = Promise.all([wealthFetch(etfActivityPath), wealthFetch(majorEtfMonitorPath)]);
    const results = [new Response("activity"), new Response("monitor")];
    calls[0]!.respond(results[0]!);
    calls[1]!.respond(results[1]!);

    expect(await pending).toEqual(results);
    expect(calls.map((call) => call.url)).toEqual([etfActivityPath, majorEtfMonitorPath]);
  });

  it.each(["together", "late"])("renews once when the two ETF requests get 401 %s", async (timing) => {
    const calls = controlledFetch();
    const dispatch = vi.spyOn(window, "dispatchEvent");
    const request = { method: "GET" };
    const activity = wealthFetch(etfActivityPath, request);
    const monitor = wealthFetch(majorEtfMonitorPath, request);
    calls[0]!.respond(expired());
    if (timing === "together") calls[1]!.respond(expired());
    await nextTask();
    expect(calls.map((call) => call.url)).toEqual([etfActivityPath, majorEtfMonitorPath, refreshPath]);
    expect(JSON.parse(calls[2]!.init!.body as string)).toEqual({ refresh_token: "old-refresh" });
    // The refresh response fields follow the auth route's TokenResponse contract.
    calls[2]!.respond(Response.json(fresh));
    await vi.waitFor(() => expect(calls).toHaveLength(timing === "together" ? 5 : 4));
    calls[3]!.respond(new Response("activity"));
    expect(await (await activity).text()).toBe("activity");
    if (timing === "late") calls[1]!.respond(expired());
    await vi.waitFor(() => expect(calls).toHaveLength(5));
    calls[4]!.respond(new Response("monitor"));

    expect(await (await monitor).text()).toBe("monitor");
    expect(calls.map((call) => call.url)).toEqual([
      etfActivityPath, majorEtfMonitorPath, refreshPath, etfActivityPath, majorEtfMonitorPath,
    ]);
    expect(calls.slice(3).map(authorization)).toEqual(["Bearer new-access", "Bearer new-access"]);
    expect(readAuthSession()?.refreshToken).toBe("new-refresh");
    expect(dispatch).not.toHaveBeenCalled();
  });

  it.each([0, 1])("lets the other request finish when waiter %i is canceled", async (canceled) => {
    const calls = controlledFetch();
    const controllers = [new AbortController(), new AbortController()];
    const paths = [etfActivityPath, majorEtfMonitorPath];
    const pending = paths.map((url, index) => wealthFetch(url, { signal: controllers[index]!.signal }));
    const denied = [expired(), expired()];
    calls[0]!.respond(denied[0]!);
    calls[1]!.respond(denied[1]!);
    await nextTask();

    controllers[canceled]!.abort();
    expect(await pending[canceled]).toBe(denied[canceled]);
    expect(calls.filter((call) => call.url === refreshPath)).toHaveLength(1);
    expect(calls[2]!.init?.signal?.aborted).toBe(false);
    calls[2]!.respond(Response.json(fresh));
    await vi.waitFor(() => expect(calls).toHaveLength(4));
    const survivor = 1 - canceled;
    expect(calls[3]!.url).toBe(paths[survivor]);
    expect(calls[3]!.init?.signal).toBe(controllers[survivor]!.signal);
    calls[3]!.respond(new Response("recovered"));
    expect(await (await pending[survivor]!).text()).toBe("recovered");
    expect(readAuthSession()?.accessToken).toBe("new-access");
  });

  it.each(["success", "failure"])("discards canceled renewal %s without disturbing a later renewal", async (outcome) => {
    const calls = controlledFetch();
    const dispatch = vi.spyOn(window, "dispatchEvent");
    const a = new AbortController();
    const b = new AbortController();
    const first = [wealthFetch(etfActivityPath, { signal: a.signal }), wealthFetch(majorEtfMonitorPath, { signal: b.signal })];
    const denied = [expired(), expired()];
    calls[0]!.respond(denied[0]!);
    calls[1]!.respond(denied[1]!);
    await nextTask();

    a.abort();
    b.abort();
    expect(calls[2]!.init?.signal?.aborted).toBe(true);
    expect(await Promise.all(first)).toEqual(denied);
    const later = [wealthFetch(etfActivityPath), wealthFetch(majorEtfMonitorPath)];
    calls[3]!.respond(expired());
    await vi.waitFor(() => expect(calls[5]?.url).toBe(refreshPath));

    if (outcome === "success") calls[2]!.respond(Response.json({ ...fresh, token: "abandoned-access" }));
    else calls[2]!.fail(new Error("abandoned connection"));
    await nextTask();
    expect(readAuthSession()?.accessToken).toBe("old-access");
    calls[4]!.respond(expired());
    await nextTask();
    expect(calls.filter((call) => call.url === refreshPath)).toHaveLength(2);
    calls[5]!.respond(Response.json(fresh));
    await vi.waitFor(() => expect(calls).toHaveLength(8));
    calls[6]!.respond(new Response("activity"));
    calls[7]!.respond(new Response("monitor"));

    expect((await Promise.all(later)).map((response) => response.status)).toEqual([200, 200]);
    expect(readAuthSession()?.accessToken).toBe("new-access");
    expect(dispatch).not.toHaveBeenCalled();
  });

  it.each(["rejected", "network"])("clears the session once when a shared renewal is %s", async (failure) => {
    const calls = controlledFetch();
    const dispatch = vi.spyOn(window, "dispatchEvent");
    const pending = Promise.all([wealthFetch(etfActivityPath), wealthFetch(majorEtfMonitorPath)]);
    const denied = [expired(), expired()];
    calls[0]!.respond(denied[0]!);
    calls[1]!.respond(denied[1]!);
    await nextTask();
    expect(calls).toHaveLength(3);
    if (failure === "rejected") calls[2]!.respond(expired());
    else calls[2]!.fail(new Error("offline"));

    expect(await pending).toEqual(denied);
    expect(calls).toHaveLength(3);
    expect(readAuthSession()).toBeNull();
    expect(dispatch).toHaveBeenCalledOnce();
    expect(dispatch.mock.calls[0]![0].type).toBe(WEALTH_AUTH_REQUIRED_EVENT);
  });

  it.each([
    ["logout", "success"], ["logout", "failure"], ["other-user", "success"], ["other-user", "failure"],
  ])("ignores shared renewal after %s, even if the old response is %s", async (change, outcome) => {
    const calls = controlledFetch();
    const dispatch = vi.spyOn(window, "dispatchEvent");
    const pending = Promise.all([wealthFetch(etfActivityPath), wealthFetch(majorEtfMonitorPath)]);
    const denied = [expired(), expired()];
    calls[0]!.respond(denied[0]!);
    calls[1]!.respond(denied[1]!);
    await nextTask();
    expect(calls).toHaveLength(3);

    if (change === "logout") clearAuthSession();
    else saveAuthSession({ ...fresh, username: "other", token: "other-access", refresh_token: "other-refresh" });
    const expected = readAuthSession();
    calls[2]!.respond(outcome === "success" ? Response.json(fresh) : expired());

    expect(await pending).toEqual(denied);
    expect(readAuthSession()).toEqual(expected);
    expect(calls).toHaveLength(3);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("shares renewal with a write but repeats only the GET", async () => {
    const calls = controlledFetch();
    const writePath = "/api/v1/wealth/market/trading-assistant/robot/candidates";
    const write = wealthFetch(writePath, { method: "POST", body: "trade" }, { replayAfterRefresh: false });
    const read = wealthFetch(etfActivityPath, { method: "GET" });
    const denied = expired();
    calls[0]!.respond(denied);
    calls[1]!.respond(expired());
    await nextTask();
    expect(calls.map((call) => call.url)).toEqual([writePath, etfActivityPath, refreshPath]);
    calls[2]!.respond(Response.json(fresh));
    expect(await write).toBe(denied);
    await vi.waitFor(() => expect(calls).toHaveLength(4));
    expect(calls[3]!.url).toBe(etfActivityPath);
    expect(calls[3]!.init?.method).toBe("GET");
    expect(authorization(calls[3]!)).toBe("Bearer new-access");
    calls[3]!.respond(new Response("activity"));
    expect(await (await read).text()).toBe("activity");
  });

  it("does not renew after an already canceled request receives its first 401", async () => {
    const calls = controlledFetch();
    const controller = new AbortController();
    const request = wealthFetch(etfActivityPath, { signal: controller.signal });
    controller.abort();
    const denied = expired();
    calls[0]!.respond(denied);
    await nextTask();
    expect(calls).toHaveLength(1);
    expect(await request).toBe(denied);
    expect(readAuthSession()?.accessToken).toBe("old-access");
  });
});
