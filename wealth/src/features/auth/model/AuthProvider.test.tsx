import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthProvider";
import { WEALTH_AUTH_REQUIRED_EVENT } from "./authEvents";
import { saveAuthSession } from "./authStorage";
import { DEFAULT_LOGIN_TIMEOUT_MS } from "./loginPolicy";

const payload = { token: "access", refresh_token: "refresh", username: "demo", is_admin: false };
const body = { username: "demo", password: "secret" };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function setup() {
  let auth!: ReturnType<typeof useAuth>;
  function Probe() { auth = useAuth(); return <output>{auth.status}</output>; }
  const result = render(<AuthProvider><Probe /></AuthProvider>);
  return { ...result, getAuth: () => auth };
}

describe("AuthProvider login lifecycle", () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("U07 restores access-token state without a /me request and clears it on auth-required", () => {
    saveAuthSession(payload);
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    const { getAuth } = setup();
    expect(getAuth().session?.accessToken).toBe("access");
    expect(screen.getByText("authenticated")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    act(() => window.dispatchEvent(new Event(WEALTH_AUTH_REQUIRED_EVENT)));
    expect(getAuth().session).toBeNull();
    expect(screen.getByText("unauthenticated")).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
  });

  it("U11 uses exactly 10000ms and rejects pre-aborted calls without a request", async () => {
    expect(DEFAULT_LOGIN_TIMEOUT_MS).toBe(10_000);
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    const { getAuth } = setup(); const controller = new AbortController(); controller.abort();
    await expect(getAuth().login(body, { signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled(); expect(localStorage.length).toBe(0);
  });

  it("U11 includes response-body parsing in the deadline and rejects ignored late parsing", async () => {
    vi.useFakeTimers();
    const parsed = deferred<typeof payload>();
    const response = new Response(); vi.spyOn(response, "json").mockReturnValue(parsed.promise);
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response); vi.stubGlobal("fetch", fetchMock);
    const { getAuth } = setup(); const controller = new AbortController();
    const result = getAuth().login(body, { signal: controller.signal }).catch((error: unknown) => error);
    await act(async () => vi.advanceTimersByTimeAsync(9999));
    expect(fetchMock.mock.calls[0]![1]!.signal!.aborted).toBe(false);
    expect(localStorage.length).toBe(0);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(await result).toMatchObject({ name: "TimeoutError", message: "登录超时，请重试" });
    expect(fetchMock.mock.calls[0]![1]!.signal!.aborted).toBe(true);
    await act(async () => parsed.resolve(payload));
    expect(getAuth().status).toBe("unauthenticated"); expect(localStorage.length).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([10_000, 10_001])("U11 rejects completion at %ims even when the timer callback is delayed", async (now) => {
    vi.useFakeTimers();
    const clock = vi.spyOn(performance, "now").mockReturnValue(0);
    const response = deferred<Response>(); vi.stubGlobal("fetch", vi.fn(() => response.promise));
    const { getAuth } = setup(); const controller = new AbortController();
    const result = getAuth().login(body, { signal: controller.signal }).catch((error: unknown) => error);
    clock.mockReturnValue(now);
    await act(async () => response.resolve(new Response(JSON.stringify(payload))));
    expect(await result).toMatchObject({ name: "TimeoutError" });
    expect(localStorage.length).toBe(0); expect(vi.getTimerCount()).toBe(0);
  });

  it("U11 commits timely success and removes its timer and external abort listener", async () => {
    vi.useFakeTimers();
    const response = deferred<Response>();
    const fetchMock = vi.fn<typeof fetch>(() => response.promise); vi.stubGlobal("fetch", fetchMock);
    const { getAuth } = setup(); const controller = new AbortController();
    const remove = vi.spyOn(controller.signal, "removeEventListener");
    const result = getAuth().login(body, { signal: controller.signal });
    await act(async () => vi.advanceTimersByTimeAsync(9999));
    await act(async () => { response.resolve(new Response(JSON.stringify(payload))); await result; });
    expect(getAuth().status).toBe("authenticated");
    expect(localStorage.getItem("wealth.auth.access-token")).toBe("access");
    // jsdom schedules zero-delay storage events for the three persisted keys.
    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(vi.getTimerCount()).toBe(0);
    expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
    controller.abort();
    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    expect(fetchMock.mock.calls[0]![1]!.signal!.aborted).toBe(false);
    expect(getAuth().status).toBe("authenticated");
  });

  it("U11 external cancellation wins over a transport AbortError and cannot save a late result", async () => {
    vi.useFakeTimers();
    const response = deferred<Response>(); const fetchMock = vi.fn<typeof fetch>(() => response.promise);
    vi.stubGlobal("fetch", fetchMock);
    const { getAuth } = setup(); const controller = new AbortController();
    const remove = vi.spyOn(controller.signal, "removeEventListener");
    const result = getAuth().login(body, { signal: controller.signal }).catch((error: unknown) => error);
    controller.abort();
    expect(await result).toMatchObject({ name: "AbortError", message: "登录已取消" });
    expect(fetchMock.mock.calls[0]![1]!.signal!.aborted).toBe(true);
    await act(async () => response.resolve(new Response(JSON.stringify(payload))));
    expect(localStorage.length).toBe(0); expect(getAuth().session).toBeNull();
    expect(remove).toHaveBeenCalledWith("abort", expect.any(Function)); expect(vi.getTimerCount()).toBe(0);
  });

  it("U11 timeout reason survives a synchronous abort-induced fetch rejection", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((_, init) => new Promise((_, reject) => {
      init!.signal!.addEventListener("abort", () => reject(new DOMException("transport canceled", "AbortError")));
    })));
    const { getAuth } = setup();
    const result = getAuth().login(body, { signal: new AbortController().signal }).catch((error: unknown) => error);
    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    expect(await result).toMatchObject({ name: "TimeoutError" }); expect(localStorage.length).toBe(0);
  });
});
