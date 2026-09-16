import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/tradingAssistantApi";
import { useWriteSession } from "./useWriteSession";

vi.mock("../api/tradingAssistantApi", async importOriginal => {
  const actual = await importOriginal<typeof api>();
  return { ...actual, getPending: vi.fn(), getRecovery: vi.fn(), getRecoverableInput: vi.fn(), request: vi.fn() };
});
const accountId = "00000000-0000-0000-0000-000000000001";
const fees = { commissionRateWan: "2.50", minimumCommission: "5.00", stampTaxRatePct: "0.05", expectedFeeVersionId: accountId };
const scope = { scopeType: "ACCOUNT_FEES" as const, accountId };
const makeStatus = (requestId: string, attemptId: string, outcome: "NOT_SAVED" | "PROCESSING" = "NOT_SAVED") => ({
  requestId, attemptId, operationType: "FEES_UPDATE" as const, scope, target: null, stateVersion: "2", outcome,
  inputRetained: true, receipt: null, rejection: null, summary: { title: "修改费率", lines: [] }, updatedAt: "2026-09-12T10:00:00+08:00",
});

describe("request-driven accounting form session", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.getPending).mockResolvedValue({ pendingRequest: null }); });
  it("checks pending writes before enabling save and never writes during lookup", async () => {
    const { result } = renderHook(() => useWriteSession(scope));
    expect(result.current.canSave).toBe(false);
    await waitFor(() => expect(result.current.canSave).toBe(true));
    expect(api.getPending).toHaveBeenCalledWith(scope, expect.any(AbortSignal));
    expect(api.request).not.toHaveBeenCalled();
  });
  it("unknown remains locked and repeated checks do not resend", async () => {
    vi.mocked(api.request).mockRejectedValue(new api.SaveOutcomeUnknown());
    vi.mocked(api.getRecovery).mockRejectedValue(new Error("unavailable"));
    const { result } = renderHook(() => useWriteSession(scope));
    await waitFor(() => expect(result.current.canSave).toBe(true));
    await act(async () => { await result.current.save("FEES_UPDATE", fees); });
    expect(result.current.canSave).toBe(false);
    await act(async () => { await result.current.check(); await result.current.save("FEES_UPDATE", fees); });
    expect(api.request).toHaveBeenCalledOnce();
    expect(result.current.recovery?.status).toBeNull();
  });
  it("only explicit restoration unlocks confirmed failure; same input gets a new attempt, not a new request", async () => {
    let originalRequest = "", originalAttempt = "";
    vi.mocked(api.request).mockImplementation(async (_path, _model, options) => {
      const body = options!.body as { requestId: string; attemptId: string };
      originalRequest ||= body.requestId; originalAttempt ||= body.attemptId;
      throw new api.SaveOutcomeUnknown();
    });
    vi.mocked(api.getRecovery).mockImplementation(async id => makeStatus(id, originalAttempt));
    vi.mocked(api.getRecoverableInput).mockImplementation(async () => ({ requestId: originalRequest, operationType: "FEES_UPDATE",
      inputSchemaVersion: "1", target: null, input: fees }));
    const { result } = renderHook(() => useWriteSession(scope));
    await waitFor(() => expect(result.current.canSave).toBe(true));
    await act(async () => { await result.current.save("FEES_UPDATE", fees); });
    expect(result.current.canSave).toBe(false);
    await act(async () => { await result.current.restore(); });
    expect(result.current.canSave).toBe(true);
    await act(async () => { await result.current.save("FEES_UPDATE", fees); });
    const second = vi.mocked(api.request).mock.calls[1][2]!.body;
    expect(second).toMatchObject({ requestId: originalRequest, expectedRequestStateVersion: "2" });
    expect((second as { attemptId: string }).attemptId).not.toBe(originalAttempt);
  });
  it("pending result from a previous account cannot block the newly selected account", async () => {
    let finish!: (value: Awaited<ReturnType<typeof api.getPending>>) => void;
    vi.mocked(api.getPending).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const { result, rerender } = renderHook(({ account }) => useWriteSession({ scopeType: "ACCOUNT_FEES", accountId: account }), { initialProps: { account: accountId } });
    rerender({ account: "00000000-0000-0000-0000-000000000002" });
    await waitFor(() => expect(result.current.canSave).toBe(true));
    await act(async () => { finish({ pendingRequest: makeStatus("old", "old", "PROCESSING") }); });
    expect(result.current.recovery).toBeNull(); expect(result.current.canSave).toBe(true);
  });
  it("reopens a rule's original close request without resending or confusing it with an edit", async () => {
    const ruleScope = { scopeType: "RULE" as const, ruleType: "PLAN" as const, ruleId: accountId };
    const requestId = crypto.randomUUID(), attemptId = crypto.randomUUID();
    const pending = { ...makeStatus(requestId, attemptId), operationType: "RULE_CLOSE" as const, scope: ruleScope };
    vi.mocked(api.getPending).mockResolvedValue({ pendingRequest: pending });
    vi.mocked(api.getRecoverableInput).mockResolvedValue({ requestId, operationType: "RULE_CLOSE",
      inputSchemaVersion: "1", target: null, input: { expectedStateVersion: "1" } });
    vi.mocked(api.request).mockRejectedValue(new api.SaveOutcomeUnknown());
    vi.mocked(api.getRecovery).mockResolvedValue(pending);
    const { result } = renderHook(() => useWriteSession(ruleScope));
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.canSave).toBe(false); expect(api.request).not.toHaveBeenCalled();
    await act(async () => { expect((await result.current.restore())?.operationType).toBe("RULE_CLOSE"); });
    await act(async () => { await result.current.save("RULE_CLOSE", { expectedStateVersion: "1" }); });
    expect(api.request).toHaveBeenCalledOnce();
    expect(vi.mocked(api.request).mock.calls[0][0]).toBe(`/plans/${accountId}/close`);
    expect(vi.mocked(api.request).mock.calls[0][2]?.body).toMatchObject({ requestId, expectedRequestStateVersion: "2" });
  });
  it("rejects retained input for a different rule operation", async () => {
    const ruleScope = { scopeType: "RULE" as const, ruleType: "PLAN" as const, ruleId: accountId };
    const requestId = crypto.randomUUID();
    vi.mocked(api.getPending).mockResolvedValue({ pendingRequest: { ...makeStatus(requestId, crypto.randomUUID()),
      operationType: "RULE_CLOSE", scope: ruleScope } });
    vi.mocked(api.getRecoverableInput).mockResolvedValue({ requestId, operationType: "RULE_CONDITIONS_UPDATE",
      inputSchemaVersion: "1", target: null, input: { expectedStateVersion: "1", priceCondition: { operator: "LTE", upper: "10.00" }, volumeCondition: null } });
    const { result } = renderHook(() => useWriteSession(ruleScope));
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => { expect(await result.current.restore()).toBeNull(); });
    expect(result.current.canSave).toBe(false); expect(api.request).not.toHaveBeenCalled();
  });
});
