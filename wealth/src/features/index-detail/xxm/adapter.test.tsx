import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildXxmViewModel, eventLabel, eventMarkerLabel } from "./adapter";
import { XxmResearchDetails, XxmLayerStatus } from "./XxmLayerUi";
import { xxmFixture } from "./xxmFixtures.test-support";

describe("XXM source adapter and user-visible details", () => {
  it("uses short chart labels while retaining directions in details", () => {
    for (const [type, direction, short, full] of [
      ["DULL", "TOP", "钝化", "顶钝化"], ["DULL", "BOTTOM", "钝化", "底钝化"],
      ["STRUCTURE", "TOP", "结构", "顶结构"], ["STRUCTURE", "BOTTOM", "结构", "底结构"],
      ["CANCEL", "TOP", "消失", "顶消失"], ["CANCEL", "BOTTOM", "取消", "底取消"],
      ["RESEARCH_HISTORICAL_WITHDRAWAL", "TOP", "结构消失", "顶结构消失"],
    ] as const) {
      expect(eventMarkerLabel({ type, direction })).toBe(short);
      expect(eventLabel({ type, direction })).toBe(full);
    }
    expect(() => eventMarkerLabel({ type: "RESEARCH_HISTORICAL_WITHDRAWAL", direction: "BOTTOM" })).toThrow();
  });
  it("preserves both events, window-external reference and historical association", () => {
    const { response, points } = xxmFixture();
    const data = buildXxmViewModel(response, points, "day", "000001.SH");
    expect(data.markers.map(marker => marker.event.type)).toEqual(["DULL", "RESEARCH_HISTORICAL_WITHDRAWAL"]);
    expect(data.byTime.get("2026-10-09")?.histories[0]?.confirmedAt).toBe("2026-09-15");
    render(<XxmResearchDetails layer={{ requestKey: "x", phase: "ready", data, errorMessage: "" }} time="2026-10-09" />);
    expect(screen.getByText("底钝化 / 顶结构消失")).toBeInTheDocument();
    expect(screen.getByText("已结束 · 价格突破")).toBeInTheDocument();
    expect(screen.getByText(/2026-02-01/)).toBeInTheDocument();
    expect(screen.getByText("-1 / -0.5")).toBeInTheDocument();
    expect(eventLabel({ type: "CANCEL", direction: "TOP" })).toBe("顶消失");
    expect(eventLabel({ type: "CANCEL", direction: "BOTTOM" })).toBe("底取消");
  });
  it("rejects identity, exact numeric, time, future, and history mismatches as a whole", () => {
    const { response, points } = xxmFixture();
    for (const mutate of [
      (r: typeof response) => { r.points[0]!.dif += 1e-10; },
      (r: typeof response) => { r.points.push(r.points[0]!); r.meta.count = 2; },
      (r: typeof response) => { r.tsCode = "399001.SZ" as typeof r.tsCode; },
      (r: typeof response) => { r.topHistories = []; },
      (r: typeof response) => { r.source.computedThrough = "2026-10-08"; r.dataStatus.asOf = "2026-10-08"; },
    ]) {
      const copy = structuredClone(response); mutate(copy);
      expect(() => buildXxmViewModel(copy, points, "day", "000001.SH")).toThrow();
    }
  });
  it("distinguishes no events, empty, delayed, and local failure", () => {
    const { response, points } = xxmFixture(); response.events = [];
    expect(buildXxmViewModel(response, points, "day", "000001.SH").markers).toEqual([]);
    const { rerender } = render(<XxmLayerStatus layer={{ requestKey: "x", phase: "loading", data: null, errorMessage: "" }} onRetry={() => {}} />);
    expect(screen.getByText("正在加载研究指标")).toBeInTheDocument();
    rerender(<XxmLayerStatus layer={{ requestKey: "x", phase: "empty", data: null, errorMessage: "" }} onRetry={() => {}} />);
    expect(screen.getByText("研究指标暂无数据")).toBeInTheDocument();
    rerender(<XxmLayerStatus layer={{ requestKey: "x", phase: "error", data: null, errorMessage: "失败" }} onRetry={() => {}} />);
    expect(screen.getByRole("button", { name: "重试研究指标" })).toBeInTheDocument();
  });
});
