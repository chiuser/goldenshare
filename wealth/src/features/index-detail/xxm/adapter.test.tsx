import type { UTCTimestamp } from "lightweight-charts";
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
      ["RESEARCH_HISTORICAL_WITHDRAWAL", "BOTTOM", "消失", "底部结构消失"],
    ] as const) {
      expect(eventMarkerLabel({ type, direction })).toBe(short);
      expect(eventLabel({ type, direction })).toBe(full);
    }
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

function bottomFixture() {
  const { response, points } = xxmFixture();
  response.topHistories = []; response.events = [];
  response.points[0]!.ordinaryState = "NONE"; response.points[0]!.ordinaryDirection = null;
  response.points[0]!.activeReference = null;
  response.bottomHistories = [{ id: "b1", structureEventId: "outside-window", confirmedAt: "2026-09-15", confirmationRoute: "dif_turn",
    originSegmentStart: "2026-09-10", leftOriginAt: "2026-09-18", priceLow: 107, priceLowAt: "2026-09-14",
    originalReference: { startTime: "2026-08-01", endTime: "2026-08-20", price: 108, dif: -5 },
    status: "ENDED", endedAt: "2026-10-09", endReason: "historical_price_break", observedThrough: "2026-10-09", ageBars: 17 }];
  response.events = [{ id: "b-event", time: "2026-10-09", direction: "BOTTOM", type: "RESEARCH_HISTORICAL_WITHDRAWAL",
    route: "historical_price_break", fromState: "NONE", eventReference: response.bottomHistories[0]!.originalReference,
    relatedTopHistoryId: null, relatedBottomHistoryId: "b1", relatedRearmId: null }];
  const prior = { ...response.points[0]!, time: "2026-10-08", pendingBottomHistoryId: "b1" };
  response.points.unshift(prior); response.meta.count = 2; response.meta.responseStart = prior.time;
  points.unshift({ ...points[0]!, time: prior.time, fullDate: prior.time });
  return { response, points };
}

it.each(["day", "m60", "m90", "m120"] as const)("renders B history at point time and disappearance on %s", period => {
  let { response, points } = bottomFixture();
  if (period !== "day") {
    const convert = (v: unknown): unknown => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v+"T15:00:00+08:00"
      : Array.isArray(v) ? v.map(convert) : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k,x]) => [k,convert(x)])) : v;
    response = convert(response) as typeof response;
    response.period = period; response.source.kind = "minute_gold"; response.source.indicatorVersion = 1;
    points = points.map(p => ({ ...p, time: (Date.parse(String(p.time)+"T15:00:00+08:00")/1000) as UTCTimestamp }));
  }
  const vm = buildXxmViewModel(response, points, period, "000001.SH", period === "day" ? null : 1);
  expect(vm.markers).toHaveLength(1);
  expect(vm.markers[0]!.dif).toBe(-1);
  expect(vm.byTime.get(String(points[0]!.time))!.bottomHistories[0]!.status).toBe("ENDED");
  expect(vm.byTime.get(String(points[1]!.time))!.bottomHistories[0]!.id).toBe("b1");
  const { unmount } = render(<XxmResearchDetails layer={{ requestKey: "b", phase: "ready", data: vm, errorMessage: "" }} time={String(points[1]!.time)} />);
  expect(screen.getByText("底部结构消失")).toBeInTheDocument();
  expect(screen.getByText("已结束 · 收盘跌破原低点")).toBeInTheDocument(); unmount();
});

it("rejects missing, orphaned, wrong-side and future B contracts, including unloaded points", () => {
  const { response, points } = bottomFixture();
  for (const mutate of [
    (r: typeof response) => { delete (r as Partial<typeof r>).bottomHistories; },
    (r: typeof response) => { delete (r.points[0] as Partial<typeof r.points[number]>).pendingBottomHistoryId; },
    (r: typeof response) => { delete (r.events[0] as Partial<typeof r.events[number]>).relatedBottomHistoryId; },
    (r: typeof response) => { r.bottomHistories = []; },
    (r: typeof response) => { r.algorithmVersion = "xxm-direction-v0.1"; },
    (r: typeof response) => { r.events[0]!.direction = "TOP"; },
    (r: typeof response) => { r.events[0]!.type = "DULL"; r.events[0]!.relatedBottomHistoryId = null; },
    (r: typeof response) => { r.events[0]!.relatedTopHistoryId = "also-top"; },
    (r: typeof response) => { r.bottomHistories[0]!.leftOriginAt = "2026-10-10"; },
    (r: typeof response) => { r.bottomHistories[0]!.priceLow = NaN; },
    (r: typeof response) => { r.bottomHistories[0]!.ageBars = -1; },
    (r: typeof response) => { r.points[0]!.pendingBottomHistoryId = "orphan-before-loaded-chart"; },
    (r: typeof response) => { r.points[1]!.pendingBottomHistoryId = "b1"; },
    (r: typeof response) => { r.events[0]!.eventReference = { ...r.events[0]!.eventReference!, dif: -6 }; },
    (r: typeof response) => { r.dataStatus.status = "EMPTY"; },
  ]) {
    const copy = structuredClone(response); mutate(copy);
    expect(() => buildXxmViewModel(copy, points.slice(1), "day", "000001.SH")).toThrow();
  }
});

it("keeps B records ending without a green event in tooltip details", () => {
  const { response, points } = bottomFixture(); response.events = [];
  response.bottomHistories[0]!.endReason = "new_bottom_DULL";
  const vm = buildXxmViewModel(response, points, "day", "000001.SH");
  expect(vm.markers).toEqual([]);
  expect(vm.byTime.get("2026-10-09")!.bottomHistories[0]!.endReason).toBe("new_bottom_DULL");
});
