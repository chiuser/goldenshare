import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DailyWaveLayerUi, DailyWaveLegend, DailyWaveResearchDetails } from "./DailyWaveLayerUi";
import { dailyWaveEmptyFixture, dailyWaveEndedFixture, dailyWaveNeutralFixture, dailyWaveReadyFixture, dailyWaveSharedLowFixture } from "./dailyWaveFixtures.test-support";
import { buildDailyWavePresentation } from "./presentation";
import type { DailyWaveReviewState } from "./types";

function state(overrides: Partial<DailyWaveReviewState> = {}): DailyWaveReviewState {
  return { supported: true, enabled: true, phase: "ready", response: dailyWaveReadyFixture(),
    candles: [], dataKey: "index:000001.SH:day:wave-review:literal-review", errorMessage: "",
    toggle: vi.fn(), retry: vi.fn(), close: vi.fn(), ...overrides };
}

describe("wave-review bottom bar and read-only explanation", () => {
  it("keeps actual range and row count accessible even when there are zero problematic segments", () => {
    const response = dailyWaveNeutralFixture();
    render(<DailyWaveLayerUi review={state({ response })} presentation={buildDailyWavePresentation(response)} />);
    expect(screen.getByRole("status")).toHaveTextContent("待核对0段");
    fireEvent.click(screen.getByRole("button", { name: "查看说明" }));
    expect(screen.getByRole("region", { name: "波段核对说明" })).toHaveTextContent(`实际范围 ${response.observationStart} — ${response.observationEnd} · ${response.sourcePoints.length}根日线`);
  });

  it("repositions an open panel when its anchor moves without resizing the chart", () => {
    const original = HTMLElement.prototype.getBoundingClientRect;
    let controlLeft = 400;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const rect = (left: number, top: number, width: number, height: number) => ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) });
      if (this.classList.contains("detail-chart-workspace")) return rect(0, 0, 900, 600);
      if (this.classList.contains("daily-wave-controls")) return rect(controlLeft, 570, 260, 24);
      if (this.classList.contains("daily-wave-state")) return rect(controlLeft + 80, 570, 150, 24);
      return original.call(this);
    });
    const response = dailyWaveReadyFixture();
    const view = buildDailyWavePresentation(response);
    const { rerender } = render(<div className="detail-chart-workspace"><DailyWaveLayerUi review={state({ response })} presentation={view} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "查看说明" }));
    const panel = screen.getByRole("region", { name: "波段核对说明" });
    expect(panel.style.left).toBe("-148px");
    controlLeft = 480;
    rerender(<div className="detail-chart-workspace"><DailyWaveLayerUi review={state({ response })} presentation={view} /></div>);
    expect(panel.style.left).toBe("-228px");
    expect(controlLeft + Number.parseFloat(panel.style.left) + Number.parseFloat(panel.style.width)).toBe(892);
    vi.restoreAllMocks();
  });
  it("shows only the toggle when closed, and nothing for unsupported subjects", () => {
    const review = state({ enabled: false, phase: "closed", response: null, dataKey: null });
    const { rerender } = render(<DailyWaveLayerUi review={review} presentation={null} />);
    fireEvent.click(screen.getByRole("button", { name: "波段核对" }));
    expect(review.toggle).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "查看说明" })).not.toBeInTheDocument();
    rerender(<DailyWaveLayerUi review={{ ...review, supported: false }} presentation={null} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("opens an explanation, retains actual dates and ID, and Escape returns focus", () => {
    const response = dailyWaveReadyFixture();
    render(<div className="detail-chart-workspace"><DailyWaveLayerUi review={state({ response })} presentation={buildDailyWavePresentation(response)} /></div>);
    const toggle = screen.getByRole("button", { name: "查看说明" });
    expect(screen.getByRole("status")).toHaveTextContent("截至2023-10-26 · 待核对1段");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    const panel = screen.getByRole("region", { name: "波段核对说明" });
    expect(panel).toHaveTextContent("实际范围 2023-10-24 — 2023-10-26 · 3根日线");
    expect(panel).toHaveTextContent("000001.SH:day:RED:2023-10-24:PRICE:UP");
    expect(panel).toHaveTextContent("2023-10-23 / 100");
    expect(panel).toHaveTextContent("尚未结束");
    fireEvent.keyDown(within(panel).getByRole("button", { name: "收起" }), { key: "Escape" });
    expect(screen.queryByRole("region", { name: "波段核对说明" })).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });

  it("closes the panel when calculation changes and preserves the mismatch explanation", () => {
    const response = dailyWaveReadyFixture();
    const view = buildDailyWavePresentation(response);
    const { rerender } = render(<DailyWaveLayerUi review={state({ response })} presentation={view} />);
    fireEvent.click(screen.getByRole("button", { name: "查看说明" }));
    rerender(<DailyWaveLayerUi review={state({ response, dataKey: "new-calculation" })} presentation={view} />);
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    rerender(<DailyWaveLayerUi review={state({ response, phase: "mismatch", dataKey: null, errorMessage: "2023-10-25的DIF不一致" })} presentation={view} />);
    expect(screen.getByRole("status")).toHaveTextContent("行情与研究结果不一致");
    fireEvent.click(screen.getByRole("button", { name: "查看说明" }));
    expect(screen.getByRole("region")).toHaveTextContent("2023-10-25的DIF不一致");
  });

  it.each(["error", "timeout"] as const)("offers an explicit retry for %s", (phase) => {
    const review = state({ phase, response: null });
    render(<DailyWaveLayerUi review={review} presentation={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("波段划分计算失败");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(review.retry).toHaveBeenCalledOnce();
  });

  it("shows the actual empty boundary without an invented observation date", () => {
    render(<DailyWaveLayerUi review={state({ phase: "empty", response: dailyWaveEmptyFixture() })} presentation={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("截至2026-10-21暂无可用日线行情");
    expect(screen.queryByRole("button", { name: "查看说明" })).not.toBeInTheDocument();
  });

  it("keeps the two original 8x6 legend assets and all endpoint facts", () => {
    const response = dailyWaveReadyFixture();
    const facts = buildDailyWavePresentation(response).byDate.get("2023-10-26")!;
    const { container } = render(<><DailyWaveLegend response={response} /><DailyWaveResearchDetails response={response} facts={facts} /></>);
    const images = container.querySelectorAll("img");
    expect(images).toHaveLength(2);
    for (const image of images) { expect(image).toHaveAttribute("width", "8"); expect(image).toHaveAttribute("height", "6"); }
    expect(screen.getByTitle("共用低点只画红色上三角，同时表示下降结束、上涨开始。")).toBeInTheDocument();
    expect(screen.getByTitle("共用高点只画绿色下三角，同时表示上涨结束、下降开始。")).toBeInTheDocument();
    const details = screen.getByLabelText("波段起止详情");
    expect(details).toHaveAttribute("tabindex", "0");
    expect(details).toHaveAttribute("data-detail-chart-interactive", "true");
    expect(details).toHaveTextContent("终止（暂定）");
    expect(details).toHaveTextContent("收盘120");
    expect(details).toHaveTextContent("最长绿柱：-2（2023-10-23）");
    expect(details).toHaveTextContent("结束确认：未确认");
    expect(details).toHaveTextContent("DIF峰 5");
  });

  it.each([
    [dailyWaveEndedFixture, "DOWN", "上涨 · 终止", "下降 · 起始",
      "000001.SH:day:RED:2023-10-24:PRICE:UP", "000001.SH:day:GREEN:2023-10-27:PRICE:DOWN", "收盘120"],
    [dailyWaveSharedLowFixture, "UP", "下降 · 终止", "上涨 · 起始",
      "000001.SH:day:GREEN:2023-10-24:PRICE:DOWN", "000001.SH:day:RED:2023-10-27:PRICE:UP", "收盘90"],
  ] as const)("keeps both original endpoint roles in hover when the shared triangle points %s", (fixture, direction, endLabel, startLabel, previousId, nextId, price) => {
    const response = fixture();
    const view = buildDailyWavePresentation(response);
    expect(view.markers.filter((m) => m.date === "2023-10-26")).toEqual([
      { date: "2023-10-26", direction, segmentIds: [previousId, nextId] },
    ]);
    render(<DailyWaveResearchDetails response={response} facts={view.byDate.get("2023-10-26")!} />);
    const details = screen.getByLabelText("波段起止详情");
    expect(within(details).getByText(endLabel, { exact: true })).toBeInTheDocument();
    expect(within(details).getByText(startLabel, { exact: true })).toBeInTheDocument();
    expect(details).toHaveTextContent(previousId);
    expect(details).toHaveTextContent(nextId);
    expect(details).toHaveTextContent(price);
    expect(details).toHaveTextContent("2023-10-26 15:00");
    expect(details.querySelectorAll("section")).toHaveLength(2);
    expect(details).not.toHaveTextContent("终止（暂定）");
  });
});
