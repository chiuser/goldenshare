import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DetailChartWorkspaceProps } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { idleNineTurnLayer } from "../../nine-turn/model/nineTurnAdapter";
import type { IndexMinuteChartViewModel } from "../model/indexDetailTypes";
import { IndexMinuteChartWorkspace } from "./IndexMinuteChartWorkspace";
import { fetchXxm } from "../xxm/apiClient";
import { xxmFixture } from "../xxm/xxmFixtures.test-support";

const workspaceMock = vi.hoisted(() => ({
  props: [] as DetailChartWorkspaceProps[],
  reset() { this.props.splice(0, this.props.length); },
}));

vi.mock("../xxm/apiClient", async (importOriginal) => ({
  ...await importOriginal<typeof import("../xxm/apiClient")>(),
  fetchXxm: vi.fn(),
}));

vi.mock("../../../shared/charts/detail-workspace/DetailChartWorkspace", () => ({
  DetailChartWorkspace: (props: DetailChartWorkspaceProps) => {
    workspaceMock.props.push(props);
    const latest = props.points.at(-1) ?? null;
    return <div>
      {props.renderMainHeader(latest)}{props.bottomBar}
      <div aria-label="普通MACD标题">{props.renderPanelHeader("macd", latest)}</div>
      {props.quantitativeStructure ? (
        <div aria-label="量化结构标题">{props.quantitativeStructure.renderHeader(null)}</div>
      ) : null}
    </div>;
  },
}));

describe("IndexMinuteChartWorkspace adapter", () => {
  beforeEach(() => {
    workspaceMock.reset();
    vi.mocked(fetchXxm).mockReset();
  });

  it("uses the index/frequency dataKey and keeps the partial message without a mock badge", () => {
    const onToggleIndicatorPanel = vi.fn();
    render(<IndexMinuteChartWorkspace recognitionEnabled data={makeData()} errorMessage="指标部分缺失" indicatorControls={{ hiddenIndicatorPanels: new Set(["kdj"]), onToggleIndicatorPanel, quantitativeStructureAvailable: false }} nineTurnLayer={idleNineTurnLayer("5")} onNineTurnRetry={vi.fn()} onRetry={vi.fn()} phase="partial" />);

    const props = latestProps();
    expect(props.dataKey).toBe("index:000001.SH:m5");
    expect(props.timeMode).toBe("minute");
    expect(props.points).toHaveLength(1);
    expect(props.mainPrimitives).toHaveLength(1);
    expect(screen.queryByText("模拟指标")).not.toBeInTheDocument();
    expect(screen.getByText("指标部分缺失")).toBeInTheDocument();
    expect(props.hiddenIndicatorPanels).toEqual(new Set(["kdj"]));
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["VOL", "MACD", "KDJ", "量化结构", "均线", "BOLL"]);
    expect(screen.getByRole("button", { name: "量化结构", pressed: false })).toBeDisabled();
    expect(props.quantitativeStructure).toBeUndefined();
    expect(fetchXxm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "VOL", pressed: true })).toHaveClass("active");
    expect(screen.getByRole("button", { name: "MACD", pressed: true })).toHaveClass("active");
    fireEvent.click(screen.getByRole("button", { name: "KDJ", pressed: false }));
    expect(onToggleIndicatorPanel).toHaveBeenCalledWith("kdj");
    fireEvent.click(screen.getByRole("button", { name: "BOLL" }));
    expect(screen.getByRole("button", { name: "BOLL" })).toHaveClass("active");
    expect(onToggleIndicatorPanel).toHaveBeenCalledTimes(1);
  });

  it("keeps empty/error module states outside the loaded shared workspace", () => {
    render(<IndexMinuteChartWorkspace recognitionEnabled data={null} errorMessage="分钟数据失败" indicatorControls={{ hiddenIndicatorPanels: new Set(), onToggleIndicatorPanel: vi.fn(), quantitativeStructureAvailable: false }} nineTurnLayer={idleNineTurnLayer("5")} onNineTurnRetry={vi.fn()} onRetry={vi.fn()} phase="error" />);
    expect(workspaceMock.props).toHaveLength(0);
    expect(screen.getByText("分钟数据失败")).toBeInTheDocument();
  });

  it("uses the 90-minute recognition values and keeps its status in the structure header", async () => {
    const { response, points } = xxmFixture("000001.SH", "m90");
    const point = points[0]!;
    const source = makeData();
    const data: IndexMinuteChartViewModel = {
      ...source, freq: 90,
      points: [{ ...source.points[0]!, fullDate: point.fullDate, time: Number(point.time),
        open: point.open, high: point.high, low: point.low, close: 106, macd: 4, dif: 6, dea: 4 }],
    };
    vi.mocked(fetchXxm).mockRejectedValueOnce(new Error("识别加载失败"))
      .mockResolvedValueOnce({ response, deadline: performance.now() + 5000 });
    const props = {
      recognitionEnabled: true, data, errorMessage: "",
      nineTurnLayer: idleNineTurnLayer("90"), onNineTurnRetry: vi.fn(), onRetry: vi.fn(), phase: "ready" as const,
    };
    const controls = { hiddenIndicatorPanels: new Set<"kdj" | "quantitativeStructure">(["kdj"]), onToggleIndicatorPanel: vi.fn(), quantitativeStructureAvailable: true };
    const rendered = render(<IndexMinuteChartWorkspace {...props} indicatorControls={controls} />);
    const header = within(screen.getByLabelText("量化结构标题"));
    const retry = await header.findByRole("button", { name: "重试顶底识别" });
    expect(within(screen.getByLabelText("普通MACD标题")).queryByRole("status")).not.toBeInTheDocument();
    expect(fetchXxm).toHaveBeenCalledTimes(1);
    fireEvent.click(retry);
    await waitFor(() => expect(latestProps().quantitativeStructure?.valuesAt(point.time)).toEqual({ macd: -2, dif: -16, dea: -15 }));
    const ready = latestProps();
    const tooltip = render(ready.renderTooltip(ready.points[0]!, "right"));
    expect(screen.getByLabelText("顶底识别详情")).toBeInTheDocument();
    expect(ready.points[0]?.macd).toBe(4);
    expect(ready.quantitativeStructure?.primitives).toHaveLength(1);
    expect(header.getByText("MACD:--")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "量化结构", pressed: true })).toBeEnabled();

    rendered.rerender(<IndexMinuteChartWorkspace {...props} indicatorControls={{ ...controls, hiddenIndicatorPanels: new Set(["quantitativeStructure"]) }} />);
    tooltip.rerender(latestProps().renderTooltip(ready.points[0]!, "right"));
    expect(screen.queryByLabelText("顶底识别详情")).not.toBeInTheDocument();
    expect(screen.getByLabelText("指数分钟K线数据提示")).toBeInTheDocument();
    expect(fetchXxm).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetchXxm).mock.calls[1]?.[0]).toEqual(vi.mocked(fetchXxm).mock.calls[0]?.[0]);
    expect(fetchXxm).toHaveBeenCalledWith(expect.objectContaining({ period: "m90", limit: 1 }), expect.any(AbortSignal));
  });
});

function latestProps() {
  const props = workspaceMock.props.at(-1);
  if (!props) throw new Error("DetailChartWorkspace was not rendered");
  return props;
}

function makeData(): IndexMinuteChartViewModel {
  return {
    tsCode: "000001.SH",
    freq: 5,
    points: [{
      time: 1_780_000_000,
      fullDate: "2026-07-31T09:30:00+08:00",
      open: 3900,
      high: 3910,
      low: 3890,
      close: 3905,
      preClose: null,
      changePct: null,
      amplitude: null,
      volume: 1000,
      volumeDisplay: null,
      amount: 2_000_000,
      ma5: 3901,
      ma10: null,
      ma20: null,
      ma30: null,
      ma60: null,
      ma90: null,
      ma250: null,
      bollUpper: null,
      bollMiddle: null,
      bollLower: null,
      macd: null,
      dif: null,
      dea: null,
      k: null,
      d: null,
      j: null,
    }],
    dataStatus: { status: "READY", code: null, expectedEndDate: "2026-07-31", observedEndDate: "2026-07-31", message: null },
    indicatorSource: "gold",
    paramsKey: "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3",
    indicatorVersion: 1,
  };
}
