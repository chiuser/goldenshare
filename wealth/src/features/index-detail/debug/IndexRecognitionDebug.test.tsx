import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { DetailChartWorkspaceProps } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { useDetailChartIndicatorControls } from "../../../shared/charts/detail-workspace/useDetailChartIndicatorControls";
import { makeOrdinaryKline, makePageInit, makeTrendPayload } from "../testing/indexDetailTestFixtures";
import { dailyWaveEndedKlineFixture, dailyWaveEndedFixture } from "../daily-wave/dailyWaveFixtures.test-support";
import { DailyWavePrimitive } from "../daily-wave/DailyWavePrimitive";
import { IndexRecognitionDebug } from "./IndexRecognitionDebug";
import { IndexChartWorkspace } from "../chart/IndexChartWorkspace";
import { useIndexDetailController } from "../controller/useIndexDetailController";
import { idleNineTurnLayer } from "../../nine-turn/model/nineTurnAdapter";
import { useNineTurnDisplayControl } from "../../nine-turn/controller/useNineTurnDisplayControl";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import { fetchDebugKline, fetchDebugPageInit } from "./apiClient";
import { toCandlePoint } from "../api/indexDetailViewModelAdapter";

const chart = vi.hoisted(() => ({ props: null as DetailChartWorkspaceProps | null }));
vi.mock("../xxm/useIndexXxmLayer", () => ({ useIndexXxmLayer: () => ({ phase: "unsupported", data: null,
  errorMessage: "", requestKey: "", retry: () => {}, macdPrimitives: [] }) }));
vi.mock("../../../shared/charts/detail-workspace/DetailChartWorkspace", () => ({
  DetailChartWorkspace: (props: DetailChartWorkspaceProps) => {
    chart.props = props;
    return <div aria-label={props.ariaLabel} data-key={props.dataKey}>
      {props.renderMainHeader(props.points.at(-1) ?? null)}{props.mainLayerAccessory}{props.bottomBar}
    </div>;
  },
}));
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); chart.props = null; });

const debugTradeDate = makeOrdinaryKline().bars.at(-1)!.tradeDate;
const debugNineTurnLayer: NineTurnLayerViewModel = {
  ...idleNineTurnLayer("day"),
  phase: "READY",
  markers: [{ tradeDate: debugTradeDate, tradeTime: null, direction: "UP", sequenceNumber: 3, completed: false }],
};

function Harness({ withHistory = false }: { withHistory?: boolean }) {
  const controller = useIndexDetailController("000001.SH", undefined, true, fetchDebugPageInit, fetchDebugKline);
  const indicatorControls = useDetailChartIndicatorControls("000001.SH");
  const nineTurnControl = useNineTurnDisplayControl("000001.SH", true);
  if (!controller.viewModel) return null;
  const history = withHistory ? {
    ...controller.history, active: true, visible: {
      candles: [...dailyWaveEndedKlineFixture().bars.map(toCandlePoint), ...controller.viewModel.chart.candles],
      nineTurnMarkers: [], trendPoints: [], failedLayers: [],
    },
  } : { ...controller.history, active: true };
  return <IndexChartWorkspace recognitionEnabled={false} MainChartAddon={IndexRecognitionDebug}
    indicatorControls={indicatorControls} nineTurnControl={nineTurnControl} nineTurnLayer={debugNineTurnLayer} onNineTurnRetry={() => {}}
    trend={controller.trend} trendPhase={controller.trendPhase} viewModel={controller.viewModel} history={history} />;
}

it("opens the wave with one request and overlays only dates loaded in the existing chart", async () => {
  const json = (payload: unknown) => new Response(JSON.stringify(payload));
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    if (url.pathname.endsWith("/debug/page-init")) return json(makePageInit());
    if (url.pathname.endsWith("/debug/kline")) return json(makeOrdinaryKline());
    if (url.pathname.endsWith("/debug/daily-waves")) return json(dailyWaveEndedFixture());
    if (url.pathname.endsWith("/trend-channel")) return json(makeTrendPayload());
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetcher);
  const drawing = vi.spyOn(DailyWavePrimitive.prototype, "setData");
  const { rerender } = render(<Harness />);
  const graph = await screen.findByLabelText("指数日线图表区");
  const before = chart.props!;
  const requestCount = fetcher.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "波段核对" }));
  await waitFor(() => expect(chart.props!.mainPrimitives).toContainEqual(expect.any(DailyWavePrimitive)));
  expect(screen.getByLabelText("指数日线图表区")).toBe(graph);
  expect(chart.props!.dataKey).toBe(before.dataKey);
  expect(chart.props!.points).toBe(before.points);
  expect(fetcher.mock.calls.slice(requestCount).map(([url]) => new URL(String(url)).pathname))
    .toEqual(["/api/v1/wealth/market/index-detail/debug/daily-waves"]);
  expect(drawing.mock.lastCall?.[0].markers).toEqual([]);
  expect(drawing.mock.lastCall?.[0].nineTurnMarkers).toEqual([
    expect.objectContaining({ time: debugTradeDate, sequenceNumber: 3 }),
  ]);
  const waveInput = drawing.mock.lastCall?.[0];
  fireEvent.click(screen.getByRole("button", { name: "九转序列", pressed: true }));
  expect(screen.getByRole("button", { name: "九转序列", pressed: false })).toBeEnabled();
  expect(drawing.mock.lastCall?.[0]).toBe(waveInput);
  expect(fetcher.mock.calls).toHaveLength(requestCount + 1);

  rerender(<Harness withHistory />);
  await waitFor(() => expect(drawing.mock.lastCall?.[0].markers.length).toBeGreaterThan(0));
  expect(chart.props!.dataKey).toBe(before.dataKey);
  expect(fetcher.mock.calls).toHaveLength(requestCount + 1);
  fireEvent.click(screen.getByRole("button", { name: "波段核对" }));
  expect(chart.props!.mainPrimitives).not.toContainEqual(expect.any(DailyWavePrimitive));
});
