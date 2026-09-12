import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTradingAccounts } from "./useTradingAccounts";
import { rememberAccountSelection } from "./accountPreference";
import type { AccountSummary } from "../api/generatedContracts";
const mock = vi.hoisted(() => ({ epoch: 1, get: vi.fn(), fetch: vi.fn() }));
vi.mock("../../auth/model/authStorage", () => ({ getAuthEpoch: () => mock.epoch }));
vi.mock("../../../shared/api/wealthApiClient", () => ({ wealthFetch: mock.fetch }));
vi.mock("../api/tradingAssistantApi", () => ({ READ_TIMEOUT_MS: 8000, getAccounts: mock.get }));
const accounts: AccountSummary[] = [1, 2].map(n => ({ accountId: `00000000-0000-4000-8000-00000000000${n}`,
  name: `账户${n}`, brokerName: "券商", initializedOn: "2026-09-12", factVersion: "1", feeVersionId: "00000000-0000-4000-8000-000000000009" }));
describe("owned account selection", () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); mock.epoch = 1;
    mock.fetch.mockResolvedValue({ ok: true, json: async () => ({ id: 12 }) }); mock.get.mockResolvedValue({ items: accounts }); });
  it("validates the owned list before restoring, and preserves ALL only in memory", async () => {
    rememberAccountSelection(12, accounts[1].accountId, accounts);
    const hook = renderHook(useTradingAccounts);
    await waitFor(() => expect(hook.result.current.state?.selected).toBe(accounts[1].accountId));
    act(() => hook.result.current.select("ALL"));
    await act(() => hook.result.current.refresh());
    expect(hook.result.current.state?.selected).toBe("ALL");
    hook.unmount();
    const reopened = renderHook(useTradingAccounts);
    await waitFor(() => expect(reopened.result.current.state?.selected).toBe(accounts[1].accountId));
  });
  it("uses the new account only after the owned list includes it", async () => {
    const hook = renderHook(useTradingAccounts);
    await waitFor(() => expect(hook.result.current.loading).toBe(false));
    await act(() => hook.result.current.refresh(accounts[1].accountId));
    expect(hook.result.current.state?.selected).toBe(accounts[1].accountId);
    expect(localStorage.getItem("wealth.ta.last-account.v1:12")).toBe(accounts[1].accountId);
  });
  it("rejects late results from another login", async () => {
    let resolve!: (value: { items: AccountSummary[] }) => void;
    mock.get.mockReturnValue(new Promise(r => { resolve = r; }));
    const hook = renderHook(useTradingAccounts);
    mock.epoch = 2;
    await act(async () => resolve({ items: accounts }));
    expect(hook.result.current.state).toBeNull(); expect(localStorage.length).toBe(0);
  });
  it("does not trust malformed identity or silently display an empty account list", async () => {
    mock.fetch.mockResolvedValue({ ok: true, json: async () => ({ id: "12" }) });
    const hook = renderHook(useTradingAccounts);
    await waitFor(() => expect(hook.result.current.error).toBe(true));
    expect(hook.result.current.state).toBeNull();
  });
});
