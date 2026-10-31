import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DetailChartWorkspaceProps } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { makeKline, makePageInit, makeTrendPayload } from "../testing/indexDetailTestFixtures";
import { dailyWaveKlineFixture, dailyWaveReadyFixture } from "../daily-wave/dailyWaveFixtures.test-support";
import { useCallback,useEffect,useState } from "react";
import { IndexRecognitionDebug } from "./IndexRecognitionDebug";
import type { IndexRecognitionDebugExtension } from "./types";
import { IndexChartWorkspace } from "../chart/IndexChartWorkspace";
import { useIndexDetailController } from "../controller/useIndexDetailController";
import { useNineTurnSeriesRegistry } from "../../nine-turn/controller/useNineTurnSeriesRegistry";
import { loadIndexNineTurnSeries } from "../api/indexNineTurnLoader";
import { IndexInfoRail } from "../sidebar/IndexInfoRail";
import type { IndexTechnicalNineTurnSummary } from "../model/indexTechnicalNineTurnSummary";
const DAILY=["day"] as const;
function Harness(){
  const controller=useIndexDetailController("000001.SH","");
  const vm=controller.viewModel;
  const [extension,setExtension]=useState<IndexRecognitionDebugExtension|null>(null);
  const owner=`000001.SH|day|${vm?.asOfTradeDate??""}`;
  const onChange=useCallback((key:string,next:IndexRecognitionDebugExtension|null)=>{if(key===owner)setExtension(next);},[owner]);
  const nine=useNineTurnSeriesRegistry({tsCode:"000001.SH",subjectType:"index",dailyLimit:1000,endDate:vm?.asOfTradeDate??null,load:loadIndexNineTurnSeries,supportedPeriods:DAILY,supportsNineTurn:vm?.capabilities.supportsNineTurn??false});
  useEffect(()=>{if(vm)void nine.ensure("day");},[!!vm,nine.ensure]);
  if(!vm)return null;
  return <><IndexRecognitionDebug ownerKey={owner} tsCode="000001.SH" activePeriod="day" ordinaryAsOfDate={vm.asOfTradeDate} supportsNineTurn={vm.capabilities.supportsNineTurn} supportsTrend={vm.capabilities.supportsTrendChannel} onChange={onChange}/>
    <IndexChartWorkspace recognition={{recognitionEnabled:true,debug:1}} debugExtension={extension??undefined} nineTurnLayer={nine.stateFor("day")} onNineTurnRetry={()=>{void nine.retry("day");}} trend={controller.trend} trendPhase={controller.trendPhase} onTrendRetry={controller.retryTrend} viewModel={vm}/>
    <IndexInfoRail activeTab="basic" nineTurnSummary={{} as IndexTechnicalNineTurnSummary} onAction={()=>{}} onNineTurnRetry={()=>{}} onTrendRetry={controller.retryTrend} onTabChange={()=>{}} pagePhase="ready" partialReasons={[]} trend={controller.trend} trendPhase={controller.trendPhase} viewModel={vm} weights={{data:null,errorMessage:"",phase:"idle",retry:()=>{}}}/></>;
}

const chart = vi.hoisted(() => ({ props: null as DetailChartWorkspaceProps | null }));
vi.mock("../xxm/useIndexXxmLayer", () => ({ useIndexXxmLayer: () => ({ phase: "unsupported", data: null,
  errorMessage: "", requestKey: "", retry: () => {}, macdPrimitives: [] }) }));
vi.mock("../../../shared/charts/detail-workspace/DetailChartWorkspace", () => ({
  DetailChartWorkspace: (props: DetailChartWorkspaceProps) => {
    chart.props = props;
    return <div aria-label={props.ariaLabel} className="detail-chart-workspace" data-key={props.dataKey}>
      {props.renderMainHeader(props.points.at(-1) ?? null)}{props.mainLayerAccessory}<div className="detail-chart-indicator-bar">{props.bottomBar}</div>
    </div>;
  },
}));
afterEach(() => { vi.unstubAllGlobals(); chart.props = null; });
const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status });

function installSource({ failResearchTrend = false, mismatch = false, researchTrend = null as Promise<Response> | null } = {}) {
  let calculations = 0;
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    if (url.pathname.endsWith("/page-init")) return json(makePageInit());
    if (url.pathname.endsWith("/daily-waves")) return json(dailyWaveReadyFixture(`review-${++calculations}`));
    if (url.pathname.endsWith("/kline")) {
      if (!url.searchParams.has("startDate")) return json(makeKline());
      const kline = dailyWaveKlineFixture();
      if (mismatch) kline.bars[1]!.factors.macd.dif = 4.01;
      return json(kline);
    }
    if (url.pathname.endsWith("/nine-turn")) return json(nineTurn(url.searchParams.get("endDate")!, Number(url.searchParams.get("limit"))));
    if (url.pathname.endsWith("/trend-channel")) {
      const end = url.searchParams.get("end_date")!;
      if (researchTrend && end === "2023-10-26") return researchTrend;
      if (failResearchTrend && end === "2023-10-26") return json({ message: "趋势暂不可用" }, 503);
      const trend = makeTrendPayload();
      if (end === "2023-10-26") {
        trend.data_status.observed_trade_date = end;
        trend.bars.forEach((bar, index) => { bar.trade_date = index ? "20231026" : "20231025"; });
      }
      return json(trend);
    }
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

describe("real extracted research controller/workspace keeps ordinary dates independent", () => {
  it("does not calculate by default; enters a matched history and returns to the retained ordinary graph", async () => {
    const fetcher = installSource();
    render(<Harness/>);
    await screen.findByRole("button", { name: "波段核对" });
    expect(chart.props?.dataKey).toBe("index:000001.SH:day");
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("/daily-waves"))).toBe(false);
    expect(chart.props?.points.at(-1)?.fullDate).toContain("2026-07-31");
    fireEvent.click(screen.getByRole("button", { name: "波段核对" }));
    await waitFor(() => expect(chart.props?.dataKey).toBe("index:000001.SH:day:wave-review:review-1"));
    expect(chart.props?.points.map((p) => p.close)).toEqual([110, 105, 120]);
    expect(chart.props?.mainPriceScalePaddingPx).toEqual({ top: 44, bottom: 44 });
    expect(screen.getByLabelText("IndexHeader")).toHaveTextContent("3940.04");
    fireEvent.click(screen.getByRole("button", { name: "查看说明" }));
    expect(screen.getByRole("region", { name: "波段核对说明" })).toHaveTextContent("2023-10-23 / 100");
    const urls = fetcher.mock.calls.map(([url]) => new URL(String(url)));
    const kline = urls.filter((url) => url.pathname.endsWith("/kline"));
    expect(kline.map((url) => [url.searchParams.get("startDate"), url.searchParams.get("endDate"), url.searchParams.get("limit")]))
      .toEqual([[null, "2026-07-31", "1000"], ["2023-10-24", "2023-10-26", "1000"]]);
    await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/nine-turn"))).toHaveLength(2));
    const nine = fetcher.mock.calls.map(([url]) => new URL(String(url))).filter((url) => url.pathname.endsWith("/nine-turn"));
    expect(nine.map((url) => [url.searchParams.get("endDate"), url.searchParams.get("limit")]))
      .toEqual([["2026-07-31", "1000"], ["2023-10-26", "1000"]]);
    fireEvent.click(screen.getByRole("button", { name: "波段核对" }));
    expect(chart.props?.dataKey).toBe("index:000001.SH:day");
    expect(chart.props?.points.at(-1)?.fullDate).toContain("2026-07-31");
    expect(chart.props?.mainPriceScalePaddingPx).toBeUndefined();
    expect(screen.queryByRole("region", { name: "波段核对说明" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/kline"))).toHaveLength(2);
  });

  it("updates asynchronous research trend without replacing primitives, lines, dataKey or selected overlay", async () => {
    let resolve!: (response: Response) => void;
    installSource({ researchTrend: new Promise<Response>(r => { resolve = r; }) });
    render(<Harness/>);
    fireEvent.click(await screen.findByRole("button", { name: "波段核对" }));
    await waitFor(() => expect(chart.props?.dataKey).toContain("wave-review"));
    const first = chart.props!;
    fireEvent.change(screen.getByLabelText("指数主图指标切换"), { target: { value: "TREND_CHANNEL" } });
    const selected = chart.props!;
    const payload = makeTrendPayload();
    payload.data_status.observed_trade_date = "2023-10-26";
    payload.bars.forEach((bar, i) => { bar.trade_date = i ? "20231026" : "20231025"; });
    await act(async () => { resolve(json(payload)); });
    await waitFor(() => expect(screen.queryByText("趋势通道加载中")).not.toBeInTheDocument());
    expect(chart.props?.dataKey).toBe(first.dataKey);
    expect(chart.props?.mainPrimitives).toBe(selected.mainPrimitives);
    expect(chart.props?.mainLines).toBe(selected.mainLines);
    expect(screen.getByLabelText("指数主图指标切换")).toHaveValue("TREND_CHANNEL");
  });

  it("leaves matched waves available when only research trend fails, and retries only its historical date", async () => {
    const fetcher = installSource({ failResearchTrend: true });
    render(<Harness/>);
    fireEvent.click(await screen.findByRole("button", { name: "波段核对" }));
    await waitFor(() => expect(chart.props?.dataKey).toContain("wave-review"));
    fireEvent.click(await screen.findByRole("button", { name: "趋势通道加载失败 · 重试" }));
    await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => String(url).includes("end_date=2023-10-26"))).toHaveLength(2));
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("end_date=2026-07-31"))).toHaveLength(1);
    expect(chart.props?.dataKey).toContain("wave-review");
    expect(screen.getByLabelText("IndexHeader")).toHaveTextContent("3940.04");
  });

  it("retains the ordinary graph on a true source difference and gives the mismatch explanation", async () => {
    installSource({ mismatch: true });
    render(<Harness/>);
    fireEvent.click(await screen.findByRole("button", { name: "波段核对" }));
    await screen.findByText("行情与研究结果不一致，暂不显示波段");
    expect(chart.props?.dataKey).toBe("index:000001.SH:day");
    expect(chart.props?.points.at(-1)?.close).toBe(3940);
    expect(chart.props?.mainPriceScalePaddingPx).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "查看说明" }));
    expect(screen.getByRole("region", { name: "波段核对说明" })).toHaveTextContent("行情与研究结果不一致");
  });

  it("closing while compute is pending aborts it and ignores its late history", async () => {
    const original = installSource();
    let resolve!: (response: Response) => void;
    let signal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/daily-waves")) {
        signal = init?.signal ?? undefined;
        return new Promise<Response>((accept) => { resolve = accept; });
      }
      return original(input);
    }));
    render(<Harness/>);
    fireEvent.click(await screen.findByRole("button", { name: "波段核对" }));
    await screen.findByText("正在计算波段划分…");
    fireEvent.click(screen.getByRole("button", { name: "波段核对" }));
    expect(signal?.aborted).toBe(true);
    await act(async () => resolve(json(dailyWaveReadyFixture())));
    expect(chart.props?.dataKey).toBe("index:000001.SH:day");
    expect(screen.queryByRole("button", { name: "查看说明" })).not.toBeInTheDocument();
  });
});

function nineTurn(endDate: string, limit: number) {
  const marker = { completed: false, direction: "UP", sequenceNumber: 3, tradeDate: endDate, tradeTime: null };
  return { dataStatus: { code: null, expectedEndDate: endDate, observedEndDate: endDate, message: null, status: "READY" }, debugInfo: null,
    latestMarker: marker, markers: [marker], period: "day", subjectType: "index", tsCode: "000001.SH",
    meta: { comparisonLag: 4, endDate, formulaVersion: 1, hasMore: false, limit, markerCount: 1, matchedRowCount: 1,
      missingRowCount: 0, nextCursor: null, observedEndDate: endDate, observedStartDate: endDate, signalThreshold: 9, sourceRowCount: 1, startDate: null } };
}
