import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/tradingAssistantApi";
import { AccountLedgerFlow } from "./AccountLedgerFlow";

vi.mock("../api/tradingAssistantApi", async original => ({ ...await original<typeof api>(), getPending: vi.fn(), request: vi.fn() }));
const id = "00000000-0000-4000-8000-000000000001";
const account = { accountId: id, name: "主账户", brokerName: "测试券商", initializedOn: "2026-09-11", factVersion: "1", feeVersionId: id };
const initial = { ...account, initializationId: id, initializationRevision: "1", initialCash: "1000.00", initialPositions: [] };
describe("initialization correction review", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.getPending).mockResolvedValue({ pendingRequest: null }); });
  it("retains the date and rejects corrections after first initialization before requesting a preview", async () => {
    const position = { clientRowId: "initial-a", tsCode: "000001.SZ", stockRef: { tsCode: "000001.SZ", name: "测试股票" },
      openedOn: "2026-09-10", quantity: 600, availableQuantity: 600, costPrice: "10.00", costAmount: "6000.00" };
    render(<AccountLedgerFlow account={account} initial={{ ...initial, initialPositions: [position] }} onClose={vi.fn()} onUpdated={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "核对更正" })).toBeEnabled());
    const date = screen.getByLabelText("建仓日期", { exact: false });
    expect(date).toHaveValue("2026-09-10");
    expect(date).toHaveAttribute("max", "2026-09-11");
    fireEvent.change(date, { target: { value: "2026-09-14" } });
    fireEvent.click(screen.getByRole("button", { name: "核对更正" }));
    expect(screen.getByText("建仓日期不能晚于首次录入日期。")).toBeInTheDocument();
    expect(date).toHaveValue("2026-09-14");
    expect(api.request).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "确认更正" })).not.toBeInTheDocument();
  });
  it("previews without saving, preserves values on back, and keeps the initialization date read only", async () => {
    vi.mocked(api.request).mockResolvedValue({ before: { initialCash: "1000.00", initialPositions: [] }, after: { initialCash: "2000.00", initialPositions: [] },
      changedFields: [{ field: "initialCash", clientRowId: null }], affectedFromDate: "2026-09-11", factVersion: "1", expectedRevision: "1", fieldErrors: [] });
    render(<AccountLedgerFlow account={account} initial={initial} onClose={vi.fn()} onUpdated={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "核对更正" })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("初始现金", { exact: false }), { target: { value: "2000.00" } });
    fireEvent.click(screen.getByRole("button", { name: "核对更正" }));
    await screen.findByText("1000.00 → 2000.00");
    expect(api.request).toHaveBeenCalledWith(`/accounts/${id}/initialization/correction-preview`, "InitializationCorrectionPreview", expect.objectContaining({
      method: "POST", body: { initialCash: "2000.00", initialPositions: [], expectedRevision: "1" } }));
    expect(api.request).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));
    expect(screen.getByLabelText("初始现金", { exact: false })).toHaveValue("2000.00");
    expect(screen.getByText(/初始化日期 2026-09-11（只读）/)).toBeInTheDocument();
  });
  it("shows historical field errors and does not open confirmation", async () => {
    vi.mocked(api.request).mockResolvedValue({ before: { initialCash: "1000.00", initialPositions: [] }, after: { initialCash: "0.00", initialPositions: [] },
      changedFields: [], affectedFromDate: "2026-09-11", factVersion: "1", expectedRevision: "1",
      fieldErrors: [{ field: "initialCash", clientRowId: null, message: "2026-09-11 的现金不足", affectedOn: "2026-09-11" }] });
    render(<AccountLedgerFlow account={account} initial={initial} onClose={vi.fn()} onUpdated={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "核对更正" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "核对更正" }));
    await screen.findByText("2026-09-11 的现金不足");
    expect(screen.queryByRole("button", { name: "确认更正" })).not.toBeInTheDocument();
  });
});
