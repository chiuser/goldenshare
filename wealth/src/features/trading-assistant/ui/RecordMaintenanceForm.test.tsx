import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/tradingAssistantApi";
import { RecordMaintenanceForm, type MaintenanceRecord } from "./RecordMaintenanceForm";
import type { AccountingWriteSession } from "./AccountingWriteFlow";

vi.mock("../api/tradingAssistantApi", async original => ({ ...await original<typeof api>(), request: vi.fn() }));
const id = "00000000-0000-4000-8000-000000000001", recordId = "00000000-0000-4000-8000-000000000002";
const account = { accountId: id, name: "主账户", brokerName: "测试券商", initializedOn: "2026-09-11", factVersion: "2", feeVersionId: id };
const cash: MaintenanceRecord = { kind: "CASH_FLOW", record: { accountRef: { accountId: id, name: "主账户", brokerName: "测试券商" }, cashFlowId: recordId,
  revision: "1", occurredOn: "2026-09-11", recordedAt: "2026-09-11T08:00:00Z", acceptedAt: "2026-09-11T08:00:00Z",
  direction: "OUT", amount: "100.00", netCashChange: "-100.00", note: null, status: "ACTIVE" } };
const session = { canSave: true, fieldErrors: [], recovery: null, save: vi.fn() } as unknown as AccountingWriteSession;
describe("record maintenance confirmation", () => {
  beforeEach(() => vi.clearAllMocks());
  it("reads a preview without saving, preserves edits on back, and saves only after confirmation", async () => {
    vi.mocked(api.request).mockResolvedValue({ before: { direction: "OUT", occurredOn: "2026-09-11", amount: "100.00", netCashChange: "-100.00", note: null },
      after: { direction: "OUT", occurredOn: "2026-09-11", amount: "200.00", netCashChange: "-200.00", note: "" },
      changedFields: [{ field: "amount", clientRowId: null }], affectedFromDate: "2026-09-11", factVersion: "2", expectedRevision: "1", fieldErrors: [] });
    render(<RecordMaintenanceForm account={account} source={cash} action="CORRECT" session={session} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("金额（元）", { exact: false }), { target: { value: "200.00" } });
    fireEvent.click(screen.getByRole("button", { name: "核对更正" }));
    await screen.findByText("100.00 → 200.00");
    expect(session.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));
    expect(screen.getByLabelText("金额（元）", { exact: false })).toHaveValue("200.00");
    fireEvent.click(screen.getByRole("button", { name: "核对更正" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认更正" }));
    expect(session.save).toHaveBeenCalledWith("CASH_FLOW_CORRECT", expect.objectContaining({ amount: "200.00", expectedRevision: "1" }),
      { kind: "CASH_FLOW", accountId: id, recordId });
  });
  it("historical cash rejection stays on the input and cannot reach confirmation", async () => {
    const facts = { direction: "OUT" as const, occurredOn: "2026-09-11", amount: "100.00", netCashChange: "-100.00", note: null };
    vi.mocked(api.request).mockResolvedValue({ before: facts, after: facts, expectedRevision: "1", factVersion: "2", affectedFromDate: "2026-09-11", changedFields: [],
      fieldErrors: [{ field: "amount", clientRowId: null, affectedOn: "2026-09-11", message: "2026-09-11 的现金不足" }] });
    render(<RecordMaintenanceForm account={account} source={cash} action="CORRECT" session={session} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "核对更正" }));
    await screen.findByText("2026-09-11 的现金不足");
    expect(screen.queryByRole("button", { name: "确认更正" })).not.toBeInTheDocument();
    expect(session.save).not.toHaveBeenCalled();
  });
  it("void is explicit, targets the source revision and has no reverse cash command", async () => {
    render(<RecordMaintenanceForm account={account} source={cash} action="VOID" session={session} onClose={vi.fn()} />);
    expect(session.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认作废" }));
    await waitFor(() => expect(session.save).toHaveBeenCalledWith("CASH_FLOW_VOID", { expectedRevision: "1" },
      { kind: "CASH_FLOW", accountId: id, recordId }));
  });
});
