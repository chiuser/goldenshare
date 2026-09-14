import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RecordFilters } from "./RecordFilters";
import { defaultRecordFilter } from "../model/recordsQuery";

describe("record filter application", () => {
  it("keeps edits local until Query and rejects inverted dates", () => {
    const query = vi.fn();
    render(<RecordFilters category="CASH" initial={defaultRecordFilter("2026-09-15")} onQuery={query} onReset={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/开始日期/), { target: { value: "2026-09-16" } });
    expect(query).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "查询" }));
    expect(query).not.toHaveBeenCalled();
    expect(screen.getByText("结束日期不得早于开始日期")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/开始日期/), { target: { value: "2026-09-10" } });
    fireEvent.change(screen.getByLabelText("资金方向"), { target: { value: "OUT" } });
    fireEvent.click(screen.getByRole("button", { name: "查询" }));
    expect(query).toHaveBeenCalledWith(expect.objectContaining({ start: "2026-09-10", direction: "OUT" }));
    expect(screen.queryByLabelText(/股票/)).not.toBeInTheDocument();
  });
});
