import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addWatchlistItem,
  fetchWatchlistMembership,
  fetchWatchlistPage,
  fetchWatchlistSummary,
  removeWatchlistItem,
  searchWatchlistCandidates,
} from "./watchlistApi";
import { page } from "../test/watchlistFixtures";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
function respond(value: unknown, status = 200) {
  const fetch = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(value), { status }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
describe("watchlist API", () => {
  it("uses Wealth auth, bounded list query and all six exact methods", async () => {
    const fetch = respond(page());
    await fetchWatchlistPage({
      tradeDate: "2026-09-02",
      afterId: 7,
      limit: 100,
    });
    const [url, init] = fetch.mock.calls[0];
    expect(new URL(url).pathname).toBe("/api/v1/wealth/market/watchlist");
    expect(new URL(url).searchParams.toString()).toBe(
      "tradeDate=2026-09-02&afterId=7&limit=100",
    );
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer test-access-token",
    );
    fetch.mockResolvedValueOnce(new Response('{"totalCount":12}'));
    expect(await fetchWatchlistSummary()).toEqual({ totalCount: 12 });
    fetch.mockResolvedValueOnce(new Response('{"keyword":"PAYH","items":[]}'));
    await searchWatchlistCandidates({ keyword: "PAYH", limit: 8 });
    expect(new URL(fetch.mock.calls[2][0]).searchParams.get("keyword")).toBe(
      "PAYH",
    );
    fetch.mockResolvedValueOnce(
      new Response('{"tsCode":"000001.SZ","isAdded":false}'),
    );
    await fetchWatchlistMembership(" 000001.sz ");
    fetch.mockResolvedValueOnce(
      new Response(
        '{"tsCode":"000001.SZ","isAdded":true,"created":true,"totalCount":1}',
      ),
    );
    await addWatchlistItem(" 000001.sz ");
    fetch.mockResolvedValueOnce(
      new Response(
        '{"tsCode":"000001.SZ","isAdded":false,"removed":true,"totalCount":0}',
      ),
    );
    await removeWatchlistItem("000001.sz");
    expect(fetch.mock.calls.map(([, options]) => options.method)).toEqual([
      "GET",
      "GET",
      "GET",
      "GET",
      "PUT",
      "DELETE",
    ]);
    expect(new URL(fetch.mock.calls[3][0]).pathname).toBe(
      "/api/v1/wealth/market/watchlist/items/000001.SZ",
    );
  });
  it("encodes path identity and preserves business errors", async () => {
    const fetch = respond(
      { code: "WL_REQUEST_INVALID", message: "股票代码非法" },
      400,
    );
    await expect(addWatchlistItem(" a/b? ")).rejects.toMatchObject({
      code: "WL_REQUEST_INVALID",
      message: "股票代码非法",
    });
    expect(fetch.mock.calls[0][0]).toContain("/items/A%2FB%3F");
  });
  it("rejects invalid/missing values instead of accepting a mock shape", async () => {
    respond({
      ...page(),
      items: [
        { ...page().items[0], moneyFlow: { netAmount: "3", direction: "UP" } },
      ],
    });
    await expect(fetchWatchlistPage()).rejects.toMatchObject({
      code: "WL_QUERY_FAILED",
    });
    respond({});
    await expect(fetchWatchlistSummary()).rejects.toMatchObject({
      code: "WL_QUERY_FAILED",
    });
  });
  it("propagates cancellation and has a 2 second search timeout", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url, options) =>
          new Promise((_resolve, reject) => {
            signals.push(options.signal);
            options.signal.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      ),
    );
    const controller = new AbortController();
    const cancelled = expect(
      fetchWatchlistSummary({ signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await cancelled;
    expect(signals[0].aborted).toBe(true);
    const timedOut = expect(
      searchWatchlistCandidates({ keyword: "PAYH" }),
    ).rejects.toMatchObject({ message: "请求超时，请重试" });
    await vi.advanceTimersByTimeAsync(1999);
    expect(signals[1].aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await timedOut;
  });
});
