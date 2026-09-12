import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { saveAuthSession } from "../../auth/model/authStorage";
import { getAccounts, request, SaveOutcomeUnknown, READ_TIMEOUT_MS, WRITE_TIMEOUT_MS } from "./tradingAssistantApi";

describe("TA request boundary", () => {
  beforeEach(() => {
    localStorage.clear();
    saveAuthSession({ token: "access", refresh_token: "refresh", username: "first", is_admin: false });
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
  it("uses the approved distinct client budgets", () => {
    expect(READ_TIMEOUT_MS).toBe(8000); expect(WRITE_TIMEOUT_MS).toBe(12000);
  });
  it("enforces the write budget even when transport ignores abort", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockReturnValue(new Promise(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    const pending = request("/accounts", "AccountCreateReceipt", { method: "POST", body: {}, write: true });
    const assertion = expect(pending).rejects.toBeInstanceOf(SaveOutcomeUnknown);
    await vi.advanceTimersByTimeAsync(WRITE_TIMEOUT_MS);
    await assertion; expect(fetchMock).toHaveBeenCalledOnce();
  });
  it("does not turn malformed successful writes into success or retry", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(request("/accounts", "AccountCreateReceipt", { method: "POST", body: {}, write: true })).rejects.toBeInstanceOf(SaveOutcomeUnknown);
    expect(fetchMock).toHaveBeenCalledOnce();
  });
  it("does not automatically send a saved command after login refresh", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response("{}", { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: "new", refresh_token: "new-refresh", username: "first", is_admin: false })));
    vi.stubGlobal("fetch", fetchMock);
    await expect(request("/accounts", "AccountCreateReceipt", { method: "POST", body: {}, write: true })).rejects.toBeInstanceOf(SaveOutcomeUnknown);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/accounts"))).toHaveLength(1);
  });
  it("drops a successful read from a previous login", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>(resolve => { finish = resolve; })));
    const pending = getAccounts();
    saveAuthSession({ token: "other", refresh_token: "other-refresh", username: "other", is_admin: false });
    finish(new Response(JSON.stringify({ items: [] })));
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
  it("a late body after cancellation cannot overwrite a new selection", async () => {
    let finish!: (value: unknown) => void;
    const response = new Response();
    response.json = () => new Promise(resolve => { finish = resolve; });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const controller = new AbortController();
    const pending = getAccounts(controller.signal);
    await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
    controller.abort(); finish({ items: [] });
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
