import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MemberViewState, SectorMemberRowViewModel } from "../model/sectorMomentumTypes";
import { SectorMemberPanel } from "./SectorMemberPanel";

describe("SectorMemberPanel", () => {
  it("renders the complete member list in one local scroll viewport", () => {
    const rows = Array.from({ length: 139 }, (_, index): SectorMemberRowViewModel => ({
      stockName: `成分股${index + 1}`,
      stockNameText: `成分股${index + 1}`,
      stockCode: `${String(index + 1).padStart(6, "0")}.SZ`,
      close: index + 1,
      closeText: (index + 1).toFixed(2),
      returnPct: 5 - index / 100,
      returnText: `${(5 - index / 100).toFixed(2)}%`,
      directionClass: "up",
    }));
    const state: MemberViewState = {
      kind: "ready",
      key: "2026-08-21|v1|BK1201.DC|20|GAINERS",
      data: {
        status: "READY",
        message: null,
        exceptionCode: null,
        tradeDate: "2026-08-21",
        hierarchyVersion: "v1",
        sectorCode: "BK1201.DC",
        sectorName: "三级行业甲",
        period: 20,
        direction: "GAINERS",
        totalMemberCount: 139,
        closeAvailableCount: 139,
        calculableCount: 139,
        rows,
      },
    };
    const { container } = render(
      <SectorMemberPanel memberState={state} onRetry={vi.fn()} period={20} sectorName="三级行业甲" />,
    );

    const table = screen.getByRole("table", { name: "三级行业成分股明细" });
    expect(within(table).getAllByRole("row")).toHaveLength(140);
    expect(screen.getByText("139 只 · 收盘 139 · 可算 139")).toBeInTheDocument();
    expect(container.querySelector(".sector-member-viewport")).toBeInTheDocument();
    expect(container.querySelectorAll(".sector-member-row")).toHaveLength(139);
  });

  it("keeps local loading, empty, and error inside the member panel", () => {
    const retry = vi.fn();
    const { rerender } = render(
      <SectorMemberPanel
        memberState={{ kind: "loading", key: "loading" }}
        onRetry={retry}
        period={5}
        sectorName="三级行业甲"
      />,
    );
    expect(screen.getByRole("status", { name: "正在加载成分股" })).toBeInTheDocument();

    rerender(
      <SectorMemberPanel
        memberState={{ kind: "empty", key: "empty", message: "empty" }}
        onRetry={retry}
        period={5}
        sectorName="三级行业甲"
      />,
    );
    expect(screen.getByText("暂无成分股数据")).toBeInTheDocument();

    rerender(
      <SectorMemberPanel
        memberState={{ kind: "error", key: "error", message: "成分股失败", retryable: true }}
        onRetry={retry}
        period={5}
        sectorName="三级行业甲"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
