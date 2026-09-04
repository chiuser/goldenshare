import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSectorDailyInsightController } from "./useSectorDailyInsightController";
import { insightJson, insightMeta, insightSnapshot } from "../testFixtures";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const navigate = vi.fn();
function hook(search = "", enabled = true) {
  return renderHook((props) => useSectorDailyInsightController({ ...props, onNavigateSearch: navigate }), { initialProps: { search, enabled } });
}
function readyFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    return insightJson(url.pathname.endsWith("/meta") ? insightMeta() : insightSnapshot(Number(url.searchParams.get("industryLevel")) as 1 | 2 | 3));
  });
}
describe("daily controller request lifecycle", () => {
  it("loads only Meta then Snapshot, changing level only reloads Snapshot", async () => {
    const fetch = readyFetch(); vi.stubGlobal("fetch", fetch);
    const { result, rerender } = hook();
    await waitFor(() => expect(result.current.viewState.kind).toBe("ready"));
    expect(fetch).toHaveBeenCalledTimes(2);
    rerender({ search: "?level=3", enabled: true });
    expect(result.current.viewState.snapshot).toBeUndefined();
    await waitFor(() => expect(result.current.viewState.snapshot?.facts.industryLevel).toBe(3));
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls.filter(([url]) => String(url).includes("/meta"))).toHaveLength(1);
  });
  it("refreshes Meta for explicit dates and never falls back from missing history", async () => {
    const fetch = readyFetch(); vi.stubGlobal("fetch", fetch);
    const { result, rerender } = hook();
    await waitFor(() => expect(result.current.viewState.kind).toBe("ready"));
    rerender({ search: "?tradeDate=2025-08-22", enabled: true });
    expect(result.current.viewState.snapshot).toBeUndefined();
    await waitFor(() => expect(result.current.viewState.kind).toBe("empty"));
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(result.current.viewState.message).toContain("尚未发布");
  });
  it("keeps published delayed facts, explicit same date is not delayed", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => insightJson(String(input).includes("/meta") ? insightMeta(true) : insightSnapshot())));
    const { result, rerender } = hook();
    await waitFor(() => expect(result.current.viewState.kind).toBe("delayed"));
    rerender({ search: "?tradeDate=2025-08-25", enabled: true });
    await waitFor(() => expect(result.current.viewState.kind).toBe("ready"));
  });
  it.each(["?debug=1", "?level=2&level=3", "?tradeDate=2025-02-30"])("invalid URL %s yields no calls", (search) => {
    const fetch = readyFetch(); vi.stubGlobal("fetch", fetch);
    expect(hook(search).result.current.viewState.kind).toBe("error"); expect(fetch).not.toHaveBeenCalled();
  });
  it("disabled route never fetches", () => { const fetch = readyFetch(); vi.stubGlobal("fetch", fetch); hook("", false); expect(fetch).not.toHaveBeenCalled(); });
  it("does not request Snapshot when no date has been published", async () => {
    const meta = insightMeta();
    meta.status = "EMPTY"; meta.defaultTradeDate = null; meta.defaultBatchKey = null; meta.hierarchyVersion = null;
    meta.dateContext.observedTradeDate = null;
    meta.tradeDates = meta.tradeDates.map((day) => ({ ...day, availability: "MISSING", batchKey: null, hierarchyVersion: null, publishedAt: null }));
    const fetch = vi.fn(async () => insightJson(meta)); vi.stubGlobal("fetch", fetch);
    const { result } = hook();
    await waitFor(() => expect(result.current.viewState.kind).toBe("empty"));
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([400, 500])("handles HTTP %s without disclosing the response body", async (status) => {
    vi.stubGlobal("fetch", vi.fn(async () => insightJson({ message: "private SQL host" }, status)));
    const { result } = hook();
    await waitFor(() => expect(result.current.viewState.kind).toBe("error"));
    expect(result.current.viewState.message).not.toContain("private");
    expect(result.current.viewState.retryable).toBe(status === 500);
  });
  it("recovers once from 409, including unchanged coverage identity", async () => {
    let snapshots = 0;
    const fetch = vi.fn(async (input: RequestInfo | URL) => String(input).includes("/meta") ? insightJson(insightMeta()) : ++snapshots === 1 ? insightJson({ message: "private" }, 409) : insightJson(insightSnapshot()));
    vi.stubGlobal("fetch", fetch);
    const { result } = hook();
    await waitFor(() => expect(result.current.viewState.kind).toBe("ready"));
    expect(fetch).toHaveBeenCalledTimes(4);
  });
  it("second 409 stops, no infinite retry and no response-body disclosure", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => String(input).includes("/meta") ? insightJson(insightMeta()) : insightJson({ message: "SELECT private SQL" }, 409));
    vi.stubGlobal("fetch", fetch);
    const { result } = hook();
    await waitFor(() => expect(result.current.viewState.kind).toBe("error"));
    expect(fetch).toHaveBeenCalledTimes(4);
    expect(result.current.viewState.message).not.toContain("SELECT");
    expect(result.current.viewState.snapshot).toBeUndefined();
  });
  it("ignores an aborted old level response and aborts on unmount", async () => {
    let resolveOld!: (r: Response) => void;
    const old = new Promise<Response>((resolve) => { resolveOld = resolve; });
    const signals: AbortSignal[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.signal) signals.push(init.signal);
      const url = String(input);
      if (url.includes("/meta")) return insightJson(insightMeta());
      if (url.includes("industryLevel=1")) return old;
      return insightJson(insightSnapshot(2));
    });
    vi.stubGlobal("fetch", fetch);
    const { result, rerender, unmount } = hook();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    rerender({ search: "?level=2", enabled: true });
    await waitFor(() => expect(result.current.viewState.snapshot?.facts.industryLevel).toBe(2));
    await act(async () => { resolveOld(insightJson(insightSnapshot(1))); await old; });
    expect(result.current.viewState.snapshot?.facts.industryLevel).toBe(2);
    expect(signals[1].aborted).toBe(true);
    unmount(); expect(signals.every((signal) => signal.aborted)).toBe(true);
  });
  it.each(["meta", "snapshot"])("times out %s after exactly 5 seconds and rejects late success", async (phase) => {
    vi.useFakeTimers();
    let resolveLate!: (r: Response) => void;
    const late = new Promise<Response>((resolve) => { resolveLate = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => phase === "snapshot" && String(input).includes("/meta") ? insightJson(insightMeta()) : late));
    const { result } = hook();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
    expect(result.current.viewState.kind).toBe("loading");
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(result.current.viewState.message).toBe("请求超时，请稍后重试。");
    await act(async () => { resolveLate(insightJson(phase === "meta" ? insightMeta() : insightSnapshot())); await late; });
    expect(result.current.viewState.kind).toBe("error");
  });
  it("routes 401 through shared auth and renders only safe feedback", async () => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn(async () => insightJson({ message: "SQL private host" }, 401)));
    const { result } = hook();
    await waitFor(() => expect(result.current.viewState.kind).toBe("error"));
    expect(result.current.viewState.message).toBe("登录已失效，请重新登录。");
    expect(result.current.viewState.retryable).toBe(false);
  });
});
