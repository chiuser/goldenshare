import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DetailChartWorkspaceProps } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { IndexMinuteChartViewModel } from "../model/indexDetailTypes";
import { IndexMinuteChartWorkspace } from "./IndexMinuteChartWorkspace";

const workspaceMock = vi.hoisted(() => ({
  props: [] as DetailChartWorkspaceProps[],
  reset() { this.props.splice(0, this.props.length); },
}));

vi.mock("../../../shared/charts/detail-workspace/DetailChartWorkspace", () => ({
  DetailChartWorkspace: (props: DetailChartWorkspaceProps) => {
    workspaceMock.props.push(props);
    return <div>{props.renderMainHeader(props.points.at(-1) ?? null)}{props.bottomBar}</div>;
  },
}));

describe("IndexMinuteChartWorkspace adapter", () => {
  beforeEach(() => workspaceMock.reset());

  it("uses the index/frequency dataKey and keeps mock indicators visible in partial state", () => {
    render(<IndexMinuteChartWorkspace data={makeData()} errorMessage="指标部分缺失" onRetry={vi.fn()} phase="partial" />);

    const props = latestProps();
    expect(props.dataKey).toBe("index:000001.SH:m5");
    expect(props.timeMode).toBe("minute");
    expect(props.points).toHaveLength(1);
    expect(screen.getAllByText("模拟指标").length).toBeGreaterThan(0);
    expect(screen.getByText("指标部分缺失")).toBeInTheDocument();
  });

  it("keeps empty/error module states outside the loaded shared workspace", () => {
    render(<IndexMinuteChartWorkspace data={null} errorMessage="分钟数据失败" onRetry={vi.fn()} phase="error" />);
    expect(workspaceMock.props).toHaveLength(0);
    expect(screen.getByText("分钟数据失败")).toBeInTheDocument();
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
    indicatorSource: "mock",
    paramsKey: "mock_index_minute_technical_v1",
    indicatorVersion: 0,
  };
}
