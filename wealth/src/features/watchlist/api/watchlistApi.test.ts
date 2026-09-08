import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./watchlistApi";
import { group, page, rules } from "../test/watchlistFixtures";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
function respond(value: unknown, status = 200) {
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify(value), {
    status
  }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
const stock = {
  tsCode: "000001.SZ",
  isAdded: false,
  groups: [{
    groupId: 1,
    name: "我的自选",
    isDefault: true,
    color: null,
    selected: false
  }]
};
describe("watchlist v2 API", () => {
  it("uses all 15 exact contracts, auth and JSON headers only for bodies", async () => {
    const cases: [() => Promise<unknown>, unknown, string, string, unknown?][] = [[() => api.fetchWatchlistGroups(), {
      groups: [group()],
      rules
    }, "GET", "/groups"], [() => api.createWatchlistGroup({
      name: "成长",
      color: rules.palette[0]
    }), {
      group: group(2)
    }, "POST", "/groups", {
      name: "成长",
      color: rules.palette[0]
    }], [() => api.changeWatchlistGroupColor(2, rules.palette[1]), {
      group: group(2)
    }, "PATCH", "/groups/2/color", {
      color: rules.palette[1]
    }], [() => api.deleteWatchlistGroup(2), {
      deletedGroupId: 2,
      deletedMemberCount: 0,
      nextGroupId: 1
    }, "DELETE", "/groups/2"], [() => api.fetchWatchlistPage({
      groupId: 1,
      cursor: "opaque",
      sortBy: "price",
      direction: "desc"
    }), page(), "GET", "/groups/1/items"], [() => api.searchWatchlistCandidates({
      groupId: 1,
      keyword: "PAYH"
    }), {
      groupId: 1,
      keyword: "PAYH",
      items: []
    }, "GET", "/groups/1/search"], [() => api.addWatchlistGroupItem(1, " 000001.sz "), {
      groupId: 1,
      tsCode: "000001.SZ",
      isAdded: true,
      created: true,
      memberCount: 1
    }, "PUT", "/groups/1/items/000001.SZ"], ...(["MOVE", "ADD_TO_GROUPS", "REMOVE", "PIN", "UNPIN"] as const).map((action, i): typeof cases[number] => [() => api.batchWatchlistItems(1, action, [3], [2]), {
      action,
      requestedCount: 1,
      createdCount: 0,
      removedCount: 0,
      updatedCount: 0,
      groupCounts: [{
        groupId: 1,
        memberCount: 1
      }]
    }, "POST", "/groups/1/actions/" + ["move", "add-to-groups", "remove", "pin", "unpin"][i], {
      membershipIds: [3],
      ...(action === "MOVE" ? {
        targetGroupId: 2
      } : action === "ADD_TO_GROUPS" ? {
        targetGroupIds: [2]
      } : {})
    }]), [() => api.fetchStockWatchlistGroups("000001.SZ"), stock, "GET", "/stocks/000001.SZ/groups"], [() => api.replaceStockWatchlistGroups("000001.SZ", [2]), {
      tsCode: "000001.SZ",
      isAdded: true,
      groupIds: [2],
      createdCount: 1,
      removedCount: 0
    }, "PUT", "/stocks/000001.SZ/groups", {
      groupIds: [2]
    }], [() => api.fetchWatchlistSummary(), {
      totalCount: 4
    }, "GET", "/summary"]];
    expect(cases).toHaveLength(15);
    for (const [call, payload, method, path, body] of cases) {
      const fetch = respond(payload);
      await call();
      const [input, init] = fetch.mock.calls[0];
      expect(new URL(input).pathname).toBe("/api/v1/wealth/market/watchlist" + path);
      expect(init.method).toBe(method);
      expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-access-token");
      expect(new Headers(init.headers).get("Content-Type")).toBe(body === undefined ? null : "application/json");
      expect(init.body).toBe(body === undefined ? undefined : JSON.stringify(body));
      expect(new URL(input).searchParams.has("afterId")).toBe(false);
    }
  });
  it.each([0, -1, 1.5, true, "1", Number.MAX_SAFE_INTEGER + 1])("rejects invalid response membership ID %s", async id => {
    const payload = page();
    (payload.items[0] as unknown as {
      membershipId: unknown;
    }).membershipId = id;
    respond(payload);
    await expect(api.fetchWatchlistPage({
      groupId: 1
    })).rejects.toMatchObject({
      code: "WL_QUERY_FAILED"
    });
  });
  it.each([(v: ReturnType<typeof page>) => ({
    ...v,
    extra: true
  }), (v: ReturnType<typeof page>) => ({
    ...v,
    nextCursor: 3
  }), (v: ReturnType<typeof page>) => ({
    ...v,
    items: [{
      ...v.items[0],
      id: 1
    }]
  }), (v: ReturnType<typeof page>) => ({
    ...v,
    items: [{
      ...v.items[0],
      quote: {
        ...v.items[0].quote,
        extra: true
      }
    }]
  }), (v: ReturnType<typeof page>) => ({
    ...v,
    dataStatus: {
      ...v.dataStatus,
      status: "BAD"
    }
  }), (v: ReturnType<typeof page>) => ({
    ...v,
    group: group(2)
  })])("rejects malformed nested v2 data", async malformed => {
    respond(malformed(page()));
    await expect(api.fetchWatchlistPage({
      groupId: 1
    })).rejects.toMatchObject({
      code: "WL_QUERY_FAILED"
    });
  });
  it.each([undefined, "1", 0, 2])("rejects missing, invalid or mismatched search group %s", async groupId => {
    respond({
      groupId,
      keyword: "A",
      items: []
    });
    await expect(api.searchWatchlistCandidates({
      groupId: 1,
      keyword: "A"
    })).rejects.toMatchObject({
      code: "WL_QUERY_FAILED"
    });
  });
  it("preserves definite errors and distinguishes uncertain writes without replay", async () => {
    respond({
      code: "WL_GROUP_NAME_CONFLICT",
      message: "同名"
    }, 409);
    await expect(api.createWatchlistGroup({
      name: "A",
      color: rules.palette[0]
    })).rejects.toMatchObject({
      code: "WL_GROUP_NAME_CONFLICT",
      message: "同名",
      outcome: "FAILED"
    });
    const fetch = respond({});
    await expect(api.addWatchlistGroupItem(1, "000001.SZ")).rejects.toMatchObject({
      outcome: "UNKNOWN"
    });
    expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockRejectedValue(new TypeError("network"));
    await expect(api.deleteWatchlistGroup(2)).rejects.toMatchObject({
      outcome: "UNKNOWN"
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    respond({
      code: "WL_WRITE_OUTCOME_UNKNOWN",
      message: "提交待确认"
    }, 503);
    await expect(api.deleteWatchlistGroup(2)).rejects.toMatchObject({
      outcome: "UNKNOWN"
    });
  });
  it("uses 2s search and 5s write timeouts and propagates external read cancellation", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn((_input, init) => new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))));
    vi.stubGlobal("fetch", fetch);
    const read = expect(api.searchWatchlistCandidates({
      groupId: 1,
      keyword: "A"
    })).rejects.toMatchObject({
      code: "WL_QUERY_FAILED"
    });
    await vi.advanceTimersByTimeAsync(2000);
    await read;
    const write = expect(api.deleteWatchlistGroup(2)).rejects.toMatchObject({
      outcome: "UNKNOWN"
    });
    await vi.advanceTimersByTimeAsync(4999);
    expect(fetch.mock.calls[1][1].signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await write;
    const controller = new AbortController();
    const cancelled = expect(api.fetchWatchlistSummary({
      signal: controller.signal
    })).rejects.toMatchObject({
      name: "AbortError"
    });
    controller.abort();
    await cancelled;
  });
  it.each([NaN, Infinity, -Infinity])("rejects non-finite numeric responses %s without converting them to null", async value => {
    const payload = page();
    payload.items[0].quote.price = value;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload
    }));
    await expect(api.fetchWatchlistPage({
      groupId: 1
    })).rejects.toMatchObject({
      code: "WL_QUERY_FAILED"
    });
  });
  it("does not claim rollback for an unclassified 500 and preserves explicit rollback codes", async () => {
    respond({
      code: "internal_error",
      message: "服务异常"
    }, 500);
    await expect(api.deleteWatchlistGroup(2)).rejects.toMatchObject({
      code: "internal_error",
      message: "服务异常",
      outcome: "UNKNOWN"
    });
    respond({
      code: "WL_WRITE_FAILED",
      message: "已回滚"
    }, 500);
    await expect(api.deleteWatchlistGroup(2)).rejects.toMatchObject({
      outcome: "FAILED"
    });
  });
  it("enforces deadline even when the transport ignores AbortSignal", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const pending = expect(api.deleteWatchlistGroup(2)).rejects.toMatchObject({
      outcome: "UNKNOWN"
    });
    await vi.advanceTimersByTimeAsync(5000);
    await pending;
    expect(vi.getTimerCount()).toBe(0);
  });
});
