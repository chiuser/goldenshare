import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DailyInsightWorkspace } from "./DailyInsightWorkspace";
import { buildSectorDailyInsightSnapshotViewModel } from "../api/sectorDailyInsightAdapter";
import { insightMeta, insightRequest, insightSnapshot } from "../testFixtures";
import type { SectorDailyInsightController } from "../model/useSectorDailyInsightController";
import type { DailyInsightViewState } from "../api/sectorDailyInsightTypes";

function controller(view?: DailyInsightViewState): SectorDailyInsightController {
  return { urlState: { market: "CN_A", tradeDate: null, level: 1 }, identity: "first", viewState: view ?? { kind: "ready", meta: insightMeta(), snapshot: buildSectorDailyInsightSnapshotViewModel(insightSnapshot(), insightRequest()) }, selectLevel: vi.fn(), selectTradeDate: vi.fn(), retry: vi.fn() };
}
describe("daily insight approved seven-column UI", () => {
  it.each([0, 1, 3, 4, 5, 80])("renders exactly %s supplied rows without placeholders or truncation", (count) => {
    const c = controller();
    c.viewState.snapshot = buildSectorDailyInsightSnapshotViewModel(insightSnapshot(1, count), insightRequest());
    render(<DailyInsightWorkspace controller={c} onNavigate={vi.fn()} />);
    expect(screen.getByRole("table", { name: "头部上涨完整列表" }).querySelectorAll(".daily-insight-row")).toHaveLength(count);
  });
  it("keeps head lists while a missing previous batch prevents comparisons", () => {
    const c = controller();
    c.viewState.snapshot!.facts.previousTradeDate = null;
    c.viewState.snapshot!.facts.summary.missingPreviousBatchCount = 337;
    c.viewState.snapshot!.strengthening = []; c.viewState.snapshot!.weakening = [];
    render(<DailyInsightWorkspace controller={c} onNavigate={vi.fn()} />);
    expect(within(screen.getByRole("table", { name: "头部上涨完整列表" })).getAllByRole("row")).toHaveLength(4);
    expect(screen.getAllByText("上一交易日事实不可比较")).toHaveLength(2);
  });
  it("renders full independent lists, centered data slots, no extra scroll hint or fake rows", () => {
    const c = controller();
    render(<DailyInsightWorkspace controller={c} onNavigate={vi.fn()} />);
    expect(screen.getAllByRole("table")).toHaveLength(4);
    const table = screen.getByRole("table", { name: "头部上涨完整列表" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getAllByRole("columnheader")).toHaveLength(7);
    for (const label of ["1日", "5日", "20日", "名次"]) expect(within(table).getByRole("columnheader", { name: label })).toHaveClass("daily-insight-centered");
    expect(screen.queryByText("列表可滚动")).not.toBeInTheDocument();
    expect(document.querySelectorAll("button.daily-insight-fact-tag")).toHaveLength(0);
    expect(screen.getByText("当日无显著转弱行业")).toBeInTheDocument();
    expect(screen.getByText(/330个行业存在缺失/)).toBeInTheDocument();
  });
  it("opens full text in a viewport dialog, navigates via evidence, restores focus", () => {
    const navigate = vi.fn();
    render(<DailyInsightWorkspace controller={controller()} onNavigate={navigate} />);
    const trigger = within(screen.getByRole("table", { name: "头部上涨完整列表" })).getByRole("button", { name: "查看通信网络设备及器件说明" });
    trigger.focus(); fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(insightSnapshot().headGainers[0].renderedText)).toBeInTheDocument();
    expect(within(dialog).getAllByRole("button")).toHaveLength(3);
    fireEvent.click(within(dialog).getByRole("button", { name: "量价分布" }));
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({ method: "price-volume", search: expect.stringContaining("tradeDate=2025-08-25") }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(trigger).toHaveFocus();
  });
  it.each(["close", "escape", "outside", "scroll"])("dismisses through %s", (kind) => {
    render(<DailyInsightWorkspace controller={controller()} onNavigate={vi.fn()} />);
    fireEvent.click(screen.getAllByRole("button", { name: "查看通信网络设备及器件说明" })[0]);
    const dialog = screen.getByRole("dialog");
    if (kind === "close") fireEvent.click(within(dialog).getByText("关闭"));
    else if (kind === "escape") fireEvent(dialog, new Event("cancel", { bubbles: false, cancelable: true }));
    else if (kind === "outside") fireEvent.click(dialog, { clientX: -1, clientY: -1 });
    else fireEvent.scroll(window);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("allows internal long-text scrolling and closes on response identity changes", () => {
    const c = controller();
    const { rerender } = render(<DailyInsightWorkspace controller={c} onNavigate={vi.fn()} />);
    fireEvent.click(screen.getAllByRole("button", { name: "查看通信网络设备及器件说明" })[0]);
    fireEvent.scroll(screen.getByRole("dialog")); expect(screen.getByRole("dialog")).toBeInTheDocument();
    rerender(<DailyInsightWorkspace controller={{ ...c, identity: "next-date-or-level" }} onNavigate={vi.fn()} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it.each([0, 1, 2])("displays exactly %s backend evidence choices", (count) => {
    const c = controller(); const row = c.viewState.snapshot!.headGainers[0];
    row.evidence = row.evidence.slice(0, count);
    render(<DailyInsightWorkspace controller={c} onNavigate={vi.fn()} />);
    fireEvent.click(screen.getAllByRole("button", { name: "查看通信网络设备及器件说明" })[0]);
    expect(within(screen.getByRole("dialog")).getAllByRole("button")).toHaveLength(count + 1);
    expect(Boolean(screen.queryByText("查看相关分析"))).toBe(count > 0);
  });
  it.each(["loading", "empty", "error"] as const)("retains toolbar and stable state surface in %s", (kind) => {
    render(<DailyInsightWorkspace controller={controller({ kind, message: "安全状态说明", retryable: true })} onNavigate={vi.fn()} />);
    expect(screen.getByLabelText("每日洞察筛选条件")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("安全状态说明")).toBeInTheDocument();
  });
});
