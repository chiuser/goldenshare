import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/tradingAssistantApi";
import { AccountLedgerFlow } from "./AccountLedgerFlow";

vi.mock("../api/tradingAssistantApi", async original => ({ ...await original<typeof api>(), getPending: vi.fn(), getRecovery: vi.fn(),
  getRecoverableInput: vi.fn(), getCashDetail: vi.fn(), request: vi.fn() }));
const id = "00000000-0000-4000-8000-000000000001", recordId = "00000000-0000-4000-8000-000000000002";
const requestId = "00000000-0000-4000-8000-000000000003", attemptId = "00000000-0000-4000-8000-000000000004";
const account = { accountId: id, name: "主账户", brokerName: "测试券商", initializedOn: "2026-09-11", factVersion: "2", feeVersionId: id };
const initial = { ...account, initializationId: id, initializationRevision: "1", initialCash: "1000.00", initialPositions: [] };
const scope = { scopeType: "ACCOUNT_LEDGER" as const, accountId: id };
const target = { kind: "CASH_FLOW" as const, accountId: id, recordId };
const baseStatus = { requestId, attemptId, operationType: "CASH_FLOW_CORRECT" as const, scope, target, stateVersion: "1", outcome: "PROCESSING" as const,
  inputRetained: true, receipt: null, rejection: null, summary: { title: "更正资金流水", lines: [] }, updatedAt: "2026-09-11T08:00:00Z" };
describe("shared account ledger recovery across entry points", () => {
  beforeEach(() => vi.clearAllMocks());
  it.each(["", null])("restores a cash correction with note %s and retains its request and target", async note => {
    vi.mocked(api.getPending).mockResolvedValue({ pendingRequest: baseStatus });
    vi.mocked(api.getRecovery).mockResolvedValue({ ...baseStatus, outcome: "NOT_SAVED", stateVersion: "2" });
    const input = { direction: "OUT" as const, occurredOn: "2026-09-11", amount: "120.00", note, expectedRevision: "1" };
    vi.mocked(api.getRecoverableInput).mockResolvedValue({ requestId, operationType: "CASH_FLOW_CORRECT", inputSchemaVersion: "1", target, input });
    const record = { accountRef: { accountId: id, name: "主账户", brokerName: "测试券商" }, cashFlowId: recordId,
      revision: "1", occurredOn: "2026-09-11", recordedAt: "2026-09-11T08:00:00Z", acceptedAt: "2026-09-11T08:00:00Z",
      direction: "OUT" as const, amount: "100.00", netCashChange: "-100.00", note: null, status: "ACTIVE" as const };
    // Only the original record is consumed during restoration; detail rendering is tested by the browser suite.
    vi.mocked(api.getCashDetail).mockResolvedValue({ record } as Awaited<ReturnType<typeof api.getCashDetail>>);
    vi.mocked(api.request).mockResolvedValueOnce({ before: { direction: "OUT", occurredOn: "2026-09-11", amount: "100.00", netCashChange: "-100.00", note: null },
      after: { direction: "OUT", occurredOn: "2026-09-11", amount: "120.00", netCashChange: "-120.00", note: "" },
      changedFields: [], expectedRevision: "1", factVersion: "2", affectedFromDate: "2026-09-11", fieldErrors: [] }).mockRejectedValue(new api.SaveOutcomeUnknown());
    render(<AccountLedgerFlow account={account} initial={initial} onClose={vi.fn()} onUpdated={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "重新核对" }));
    fireEvent.click(await screen.findByRole("button", { name: "返回编辑" }));
    await screen.findByRole("heading", { name: "更正资金流水" });
    expect(screen.queryByRole("heading", { name: "更正期初资产" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("金额（元）", { exact: false })).toHaveValue("120.00");
    expect(api.request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "核对更正" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认更正" }));
    await waitFor(() => expect(api.request).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.request).mock.calls[1]).toEqual([`/accounts/${id}/cash-flows/${recordId}/corrections`, "CashCorrectReceipt",
      expect.objectContaining({ write: true, body: { ...input, requestId, attemptId: expect.any(String), expectedRequestStateVersion: "2" } })]);
  });
});
