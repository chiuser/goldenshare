import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SectorMomentumDetailResponse } from "../model/sectorMomentumTypes";
import { SelectedSectorSummary } from "./SelectedSectorSummary";

describe("SelectedSectorSummary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("uses a second compact tier for a longer identity and restores the design font when space returns", () => {
    let constrained = true;
    let notifyResize: (() => void) | undefined;

    class ResizeObserverMock {
      constructor(callback: ResizeObserverCallback) {
        notifyResize = () => callback([], this as unknown as ResizeObserver);
      }

      observe() {}
      disconnect() {}
    }

    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(function (this: HTMLElement) {
      const identity = this.closest(".momentum-selected-identity");
      const extraCompact = identity?.classList.contains("extra-compact") ?? false;
      const compact = identity?.classList.contains("compact") ?? false;
      if (this.textContent === "通信网络设备及器件") return extraCompact ? 108 : compact ? 126 : 153;
      if (this.textContent === "通信 > 通信设备 > 通信网络设备及器件") return extraCompact ? 155 : compact ? 174 : 210;
      return 0;
    });
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (this: HTMLElement) {
      const identity = this.closest(".momentum-selected-identity");
      const extraCompact = identity?.classList.contains("extra-compact") ?? false;
      const compact = identity?.classList.contains("compact") ?? false;
      if (this.textContent === "通信网络设备及器件") return constrained ? extraCompact ? 116 : compact ? 111 : 106 : 180;
      if (this.textContent === "通信 > 通信设备 > 通信网络设备及器件") return constrained ? 167 : 220;
      return 0;
    });

    render(<SelectedSectorSummary detail={detail()} />);

    const identity = screen.getByText("通信网络设备及器件").closest(".momentum-selected-identity");
    expect(identity).toHaveClass("compact", "extra-compact");
    expect(screen.getByText("3级行业")).toBeInTheDocument();
    expect(screen.getByText("通信 > 通信设备 > 通信网络设备及器件")).toBeInTheDocument();

    constrained = false;
    act(() => notifyResize?.());
    expect(identity).not.toHaveClass("compact");
  });
});

function detail(): SectorMomentumDetailResponse {
  return {
    sectorCode: "BK1201.DC",
    sectorName: "通信网络设备及器件",
    industryLevel: 3,
    hierarchyPath: "通信 > 通信设备 > 通信网络设备及器件",
    scopeTitle: "三级行业总榜",
    returnPct: 41.15,
    percentile: 100,
    currentScopeStrengthRank: 1,
    currentScopeCalculableCount: 4,
    currentScopeTotalCount: 4,
    globalLevelStrengthRank: 3,
    globalLevelCalculableCount: 337,
    globalLevelTotalCount: 337,
    parentStrengthRank: 1,
    parentCalculableCount: 4,
    parentTotalCount: 4,
    formulaKey: "sector-cross-sectional-momentum",
    formulaVersion: 1,
    hierarchyVersion: "v1",
  };
}
