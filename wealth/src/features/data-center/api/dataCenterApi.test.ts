import { afterEach, expect, it, vi } from "vitest";
import { dataCenterApi, DataCenterApiError, request } from "./dataCenterApi";
import { saveAuthSession } from "../../auth/model/authStorage";
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }); }
it("date preview and command contain no company, keyword, URL, path or selected query", async () => {
  const fetcher = vi.fn().mockImplementation(async () => response({})); vi.stubGlobal("fetch", fetcher);
  await dataCenterApi.createPreview({ startDate: "2026-09-30", endDate: "2026-09-30", intervalSeconds: 0 });
  await dataCenterApi.createRun("preview", "fixed-intent");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ startDate: "2026-09-30", endDate: "2026-09-30", intervalSeconds: 0 });
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ previewId: "preview" });
  expect(fetcher.mock.calls[1][1].headers.get("Idempotency-Key")).toBe("fixed-intent");
});
it("precise retries and checks use the approved namespace", async () => {
  const fetcher = vi.fn().mockImplementation(async () => response({})); vi.stubGlobal("fetch", fetcher);
  await dataCenterApi.retry("root", "a".repeat(64), "same-key"); await dataCenterApi.retry("root", null, "another-key"); await dataCenterApi.recheck("root", "remoteSource");
  expect(fetcher.mock.calls.map(c => JSON.parse(c[1].body))).toEqual([{ scope: "singleFailed", artifactKey: "a".repeat(64) }, { scope: "allFailed" }, { kind: "remoteSource" }]);
  expect(fetcher.mock.calls.every(c => c[0].startsWith("/api/v1/wealth/data-center/announcements/runs/root/"))).toBe(true);
});
it("preserves public 409 for preview invalidation", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ code: "DC_PREVIEW_STALE", message: "请重新预览" }, 409)));
  await expect(dataCenterApi.createRun("preview", "key")).rejects.toMatchObject({ status: 409, code: "DC_PREVIEW_STALE", message: "请重新预览" });
});
it("GET pagination is bounded and retains query identity", async () => {
  const fetcher = vi.fn().mockImplementation(async () => response({})); vi.stubGlobal("fetch", fetcher);
  await dataCenterApi.query("q-1", 2); await dataCenterApi.history("123"); await dataCenterApi.files("root", "failed", "a".repeat(64));
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/wealth/data-center/announcements/queries/q-1?page=2");
  expect(fetcher.mock.calls[1][0]).toContain("limit=20"); expect(fetcher.mock.calls[2][0]).toContain("limit=50");
  expect(fetcher.mock.calls.every(c => c[1].method !== "POST")).toBe(true);
});
it("five second timeout aborts observation without a stop or replay command", async () => {
  vi.useFakeTimers(); const fetcher = vi.fn((_path, init) => new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))));
  vi.stubGlobal("fetch", fetcher); const pending = request("/api/v1/wealth/data-center/modules");
  const assertion = expect(pending).rejects.toThrow("请求超时"); await vi.advanceTimersByTimeAsync(5000); await assertion; expect(fetcher).toHaveBeenCalledTimes(1);
});
it("401 flows through existing auth refresh and retains command body/key", async () => {
  saveAuthSession({ token: "old", refresh_token: "refresh", username: "test", is_admin: false });
  const fetcher = vi.fn().mockResolvedValueOnce(response({}, 401)).mockResolvedValueOnce(response({ token: "new", refresh_token: "refresh2", username: "test", is_admin: false })).mockResolvedValueOnce(response({ runId: "same" })); vi.stubGlobal("fetch", fetcher);
  await dataCenterApi.createRun("preview", "intent"); expect(fetcher.mock.calls[1][0]).toBe("/api/v1/auth/refresh");
  expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[2][1].body); expect(fetcher.mock.calls[2][1].headers.get("Idempotency-Key")).toBe("intent");
});
it("does not silently translate failed reads into empty modules", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ code: "DC_SOURCE_UNAVAILABLE", message: "来源不可读取" }, 503)));
  await expect(dataCenterApi.modules()).rejects.toBeInstanceOf(DataCenterApiError);
});

it("candidate lookup projects date fields even if caller supplies a full draft object", async () => {
  const fetcher = vi.fn().mockImplementation(async () => response({})); vi.stubGlobal("fetch", fetcher);
  const draft = { startDate: "2026-09-30", endDate: "2026-09-30", downloadStatus: "all", titleKeyword: "董事会", tsCode: "600000.SH" };
  await dataCenterApi.companies("PAYH", draft);
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/wealth/data-center/announcements/companies?keyword=PAYH&startDate=2026-09-30&endDate=2026-09-30");
});
