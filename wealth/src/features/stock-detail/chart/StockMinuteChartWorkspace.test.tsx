import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DetailChartWorkspaceProps } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { StockMinuteChartViewModel } from "../api/stockMinuteViewModelAdapter";

import { StockMinuteChartWorkspace } from "./StockMinuteChartWorkspace";

const workspaceMock = vi.hoisted(() => ({
  props: [] as DetailChartWorkspaceProps[],
  reset() {
    this.props.splice(0, this.props.length);
  },
}));

vi.mock("../../../shared/charts/detail-workspace/DetailChartWorkspace", () => ({
  DetailChartWorkspace: (props: DetailChartWorkspaceProps) => {
    workspaceMock.props.push(props);
    const latest = props.points.at(-1) ?? null;
    return (
      <div aria-label={props.ariaLabel} data-testid="shared-detail-workspace">
        {props.topRightAccessory}
        {props.renderMainHeader(latest)}
        {props.renderPanelHeader("macd", latest)}
        {props.renderPanelHeader("volume", latest)}
        {props.renderPanelHeader("kdj", latest)}
      </div>
    );
  },
}));

describe("StockMinuteChartWorkspace", () => {
  beforeEach(() => workspaceMock.reset());

  it("maps the complete minute contract into shared points without fabricating daily fields", () => {
    const data = makeMinuteData(2);
    data.points[1]!.macdDif = null;
    data.points[1]!.kdjJ = null;

    render(<StockMinuteChartWorkspace loadState="ready" data={data} />);

    const props = latestWorkspaceProps();
    expect(props.points).toHaveLength(2);
    expect(props.points[1]).toMatchObject({
      time: data.points[1]!.timestamp,
      fullDate: data.points[1]!.tradeTime,
      open: data.points[1]!.open,
      high: data.points[1]!.high,
      low: data.points[1]!.low,
      close: data.points[1]!.close,
      volume: data.points[1]!.volume,
      amount: data.points[1]!.amount,
      dif: null,
      dea: data.points[1]!.macdDea,
      macd: data.points[1]!.macd,
      k: data.points[1]!.kdjK,
      d: data.points[1]!.kdjD,
      j: null,
      preClose: null,
      changePct: null,
      amplitude: null,
      turnoverRate: null,
      overlays: {},
    });
    expect(props.mainLines).toEqual([]);
  });

  it("selects the frozen M1 display strategies and keeps the status accessory", () => {
    const data = makeMinuteData(1);
    data.points[0]!.macdDif = null;
    data.indicatorStatus = {
      status: "DELAYED",
      expectedEndDate: "2026-07-31",
      observedEndDate: "2026-07-30",
      message: "指标尚未覆盖页面期望交易日。",
    };

    render(<StockMinuteChartWorkspace loadState="ready" data={data} />);

    const props = latestWorkspaceProps();
    expect(props).toMatchObject({
      ariaLabel: "分钟图表区",
      crosshairPresentation: "native-axis-labels",
      dataKey: "stock:000638.SZ:m5",
      timeAxisAriaLabel: "股票分钟底部时间轴",
      timeAxisPlacement: "each-pane",
      timeMode: "minute",
    });
    expect("bottomBar" in props).toBe(false);
    expect(screen.getByRole("status")).toHaveTextContent("指标尚未覆盖页面期望交易日。");
    expect(screen.getByRole("status")).toHaveTextContent("freq=5");
    expect(screen.getByText("DIF:--")).toBeInTheDocument();
  });

  it("preserves minute tooltip field order, units and candle-relative colors", () => {
    const data = makeMinuteData(1);
    const source = data.points[0]!;
    source.open = 10;
    source.close = 11;
    source.high = 11.5;
    source.low = 9.5;
    source.volume = 764_100;
    source.amount = 7_294_676;
    render(<StockMinuteChartWorkspace loadState="ready" data={data} />);

    const props = latestWorkspaceProps();
    render(<>{props.renderTooltip(props.points[0]!, "left")}</>);

    const tooltip = screen.getByLabelText("分钟K线数据提示");
    expect(tooltip).toHaveClass("left");
    const rows = within(tooltip).getAllByRole("generic").filter((node) => node.classList.contains("tooltip-row"));
    expect(rows.map((row) => row.querySelector("span")?.textContent)).toEqual([
      "时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额",
    ]);
    expect(within(tooltip).getByText("20260731 09:30")).toBeInTheDocument();
    expect(within(tooltip).getByText("10.00")).toHaveClass("flat");
    expect(within(tooltip).getByText("11.00")).toHaveClass("up");
    expect(within(tooltip).getByText("76.41万股")).toBeInTheDocument();
    expect(within(tooltip).getByText("729.47万元")).toBeInTheDocument();
    expect(within(tooltip).queryByText("涨幅")).not.toBeInTheDocument();
    expect(within(tooltip).queryByText("换手率")).not.toBeInTheDocument();
  });

  it.each([
    ["idle", undefined, "暂无分钟数据"],
    ["loading", undefined, "正在加载分钟数据"],
    ["error", "读取失败", "读取失败"],
  ] as const)("keeps the %s module state outside the loaded shared chart", (loadState, errorMessage, expected) => {
    render(<StockMinuteChartWorkspace loadState={loadState} data={null} errorMessage={errorMessage} />);

    expect(screen.getByRole("status")).toHaveTextContent(expected);
    expect(screen.queryByTestId("shared-detail-workspace")).not.toBeInTheDocument();
    expect(workspaceMock.props).toHaveLength(0);
  });
});

function latestWorkspaceProps(): DetailChartWorkspaceProps {
  const props = workspaceMock.props.at(-1);
  if (!props) throw new Error("DetailChartWorkspace was not rendered");
  return props;
}

function makeMinuteData(count: number): StockMinuteChartViewModel {
  return {
    tsCode: "000638.SZ",
    freq: 5,
    points: Array.from({ length: count }, (_, index) => {
      const minuteOfDay = 9 * 60 + 30 + index;
      const hour = String(Math.floor(minuteOfDay / 60)).padStart(2, "0");
      const minute = String(minuteOfDay % 60).padStart(2, "0");
      const tradeTime = `2026-07-31T${hour}:${minute}:00+08:00`;
      return {
        key: tradeTime,
        timestamp: 1_780_000_000 + index * 300,
        tradeTime,
        open: 10 + index,
        high: 11 + index,
        low: 9 + index,
        close: 10.5 + index,
        volume: 100 + index,
        amount: 1000 + index,
        macdDif: 0.1,
        macdDea: 0.2,
        macd: 0.3,
        kdjK: 20,
        kdjD: 30,
        kdjJ: 10,
      };
    }),
    dataStatus: {
      status: "READY",
      expectedEndDate: "2026-07-31",
      observedEndDate: "2026-07-31",
      message: null,
    },
    indicatorStatus: {
      status: "READY",
      expectedEndDate: "2026-07-31",
      observedEndDate: "2026-07-31",
      message: null,
    },
  };
}
