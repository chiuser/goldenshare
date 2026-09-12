import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { WriteRecoveryState } from "../model/writeRecovery";
import { WriteRecoveryDialog } from "./WriteRecoveryDialog";

const state: WriteRecoveryState = { authEpoch: 1, pageGeneration: 1, requestId: "request", status: null,
  queryUnavailable: false, inconsistentResponse: false };
describe("R11 recovery controls", () => {
  it("unknown has only read-check and close, never a save action", () => {
    const check = vi.fn(), edit = vi.fn();
    render(<WriteRecoveryDialog state={state} checking={false} onCheck={check} onEdit={edit} onClose={vi.fn()} onLoadDetails={vi.fn()} />);
    expect(screen.getByText(/输入尚未安全保留/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新核对" }));
    expect(check).toHaveBeenCalledOnce(); expect(edit).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "返回编辑" })).not.toBeInTheDocument();
  });
});
