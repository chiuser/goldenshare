import { toDetailChartPoint } from "./indexChartPointAdapter";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { IndexDailyHistory } from "../controller/useIndexDailyHistory";
import type { IndexRecognitionProps, IndexRecognitionDebugExtension } from "../debug/types";
import { useIndexXxmLayer } from "../xxm/useIndexXxmLayer";
import { QUANTITATIVE_STRUCTURE_TITLE, useXxmValuesAt, XxmLayerStatus, XxmSignalDetails } from "../xxm/XxmLayerUi";

import { useNineTurnChartLayer } from "../../nine-turn/controller/useNineTurnChartLayer";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import { NineTurnLayerStatus } from "../../nine-turn/ui/NineTurnLayerStatus";
import { DetailChartIndicatorToggle } from "../../../shared/charts/detail-workspace/DetailChartIndicatorToggle";
import { DetailChartWorkspace } from "../../../shared/charts/detail-workspace/DetailChartWorkspace";
import { DETAIL_CHART_COLORS, isFiniteChartNumber } from "../../../shared/charts/detail-workspace/detailChartSeries";
import type {
  DetailChartIndicatorControls,
  DetailChartLineDefinition,
  DetailChartMacdValues,
  DetailChartPanelKey,
  DetailChartPoint,
  DetailChartTooltipSide,
} from "../../../shared/charts/detail-workspace/detailChartTypes";
import { directionClass } from "../../../shared/lib/marketDirection";
import type { MarketDirection } from "../../../shared/model/market";
import { TrendChannelPanePrimitive } from "../../../shared/charts/trend-channel/TrendChannelPanePrimitive";
import { buildTrendChannelLines } from "../../../shared/charts/trend-channel/trendChannelGeometry";
import type {
  IndexDetailViewModel,
  IndexMainOverlay,
  TrendChannelViewModel,
} from "../model/indexDetailTypes";

interface IndexChartWorkspaceProps {
  indicatorControls: DetailChartIndicatorControls;
  nineTurnLayer: NineTurnLayerViewModel;
  onNineTurnRetry: () => void;
  trend: TrendChannelViewModel | null;
  trendPhase: "unavailable" | "loading" | "ready" | "error";
  viewModel: IndexDetailViewModel;
  recognition: IndexRecognitionProps;
  debugExtension?: IndexRecognitionDebugExtension;
  onTrendRetry?: () => void;
  history?: IndexDailyHistory;
}

export function IndexChartWorkspace({
  indicatorControls,
  nineTurnLayer: ordinaryNineTurn,
  onNineTurnRetry: ordinaryNineTurnRetry,
  trend: ordinaryTrend,
  trendPhase: ordinaryTrendPhase,
  viewModel,
  recognition,
  debugExtension,
  onTrendRetry: ordinaryTrendRetry,
  history,
}: IndexChartWorkspaceProps) {
  const ownerKey = `${viewModel.identity.tsCode}|day|${viewModel.asOfTradeDate}`;
  const extension = recognition.debug === 1 && debugExtension?.ownerKey === ownerKey ? debugExtension : null;
  const research = extension?.chartOverride ?? null;
  const activeHistory = !research && history?.active ? history : undefined;
  const historical = activeHistory?.visible;
  const firstDate = activeHistory ? viewModel.chart.candles[0]?.time : undefined;
  const lastDate = activeHistory ? viewModel.chart.candles.at(-1)?.time : undefined;
  const nineTurnLayer = useMemo(() => {
    if (research) return research.nineTurnLayer;
    if (!firstDate || !lastDate) return ordinaryNineTurn;
    const initial = ordinaryNineTurn.markers.filter(marker => firstDate <= marker.tradeDate && marker.tradeDate <= lastDate);
    return { ...ordinaryNineTurn, markers: [...(historical?.nineTurnMarkers ?? []), ...initial] };
  }, [firstDate, lastDate, historical?.nineTurnMarkers, ordinaryNineTurn, research]);
  const trend = useMemo(() => {
    if (research) return research.trend;
    if (!firstDate || !lastDate) return ordinaryTrend;
    if (!ordinaryTrend && !historical?.trendPoints.length) return null;
    const initial = ordinaryTrend?.points.filter(point => firstDate <= point.time && point.time <= lastDate) ?? [];
    return {
      points: [...(historical?.trendPoints ?? []), ...initial],
      droppedCount: ordinaryTrend?.droppedCount ?? 0,
      status: ordinaryTrend?.status ?? "READY",
    } satisfies TrendChannelViewModel;
  }, [firstDate, lastDate, historical?.trendPoints, ordinaryTrend, research]);
  const trendPhase = research?.trendPhase ?? ordinaryTrendPhase;
  const onNineTurnRetry = research?.onNineTurnRetry ?? ordinaryNineTurnRetry;
  const onTrendRetry = research?.onTrendRetry ?? ordinaryTrendRetry;
  const supportsTrend = viewModel.capabilities.supportsTrendChannel && viewModel.identity.tsCode === "000001.SH";
  const [selection, setSelection] = useState<{ owner: string; overlay: IndexMainOverlay } | null>(null);
  const overlay = selection?.owner === ownerKey ? selection.overlay : supportsTrend && ordinaryTrend ? "TREND_CHANNEL" : "MA";
  const setOverlay = (overlay: IndexMainOverlay) => setSelection({ owner: ownerKey, overlay });
  const initialCandles = research?.candles ?? viewModel.chart.candles;
  const initialPoints = useMemo(() => initialCandles.map(toDetailChartPoint), [initialCandles]);
  const historicalCandles = historical?.candles;
  const points = useMemo(() => historicalCandles?.map(toDetailChartPoint) ?? initialPoints, [historicalCandles, initialPoints]);
  const dataKey = research?.dataKey ?? (activeHistory ? `index:${ownerKey}` : `index:${viewModel.identity.tsCode}:day`);
  const xxm = useIndexXxmLayer({ tsCode: viewModel.identity.tsCode, period: "day", points: initialPoints, enabled: recognition.recognitionEnabled, debug: recognition.debug, decodeDebug: recognition.decodeXxmDebug });
  const valuesAt = useXxmValuesAt(xxm.data);
  const structureVisible = indicatorControls.quantitativeStructureAvailable
    && !indicatorControls.hiddenIndicatorPanels.has("quantitativeStructure");
  const nineTurnChartLayer = useNineTurnChartLayer({ dataKey, layer: nineTurnLayer, points, timeMode: "daily" });
  const trendByTime = useMemo(() => new Map((trend?.points ?? []).map((point) => [point.time, point])), [trend]);
  const mainLines = useMemo(() => overlay === "MA" ? buildMaLines() : overlay === "BOLL" ? buildBollLines() : [], [overlay]);
  const ordinaryTrendPrimitive = useMemo(() => new TrendChannelPanePrimitive([]), [dataKey]);
  useEffect(() => {
    ordinaryTrendPrimitive.setLines(!research && trend ? buildTrendChannelLines(trend.points, points.map(p => String(p.time))) : []);
  }, [ordinaryTrendPrimitive, research !== null, points, trend]);
  const ordinaryTrendPrimitives = useMemo(() => overlay === "TREND_CHANNEL" ? [ordinaryTrendPrimitive] : [], [overlay, ordinaryTrendPrimitive]);
  const mainPrimitives = useMemo(() => [...(overlay === "TREND_CHANNEL" ? research?.trendMainPrimitives ?? ordinaryTrendPrimitives : []), ...nineTurnChartLayer.mainPrimitives, ...(research?.waveMainPrimitives ?? [])], [overlay, research?.trendMainPrimitives, research?.waveMainPrimitives, ordinaryTrendPrimitives, nineTurnChartLayer.mainPrimitives]);

  return (
    <DetailChartWorkspace
      ariaLabel="指数日线图表区"
      bottomBar={<div className={extension ? "daily-wave-bottom-bar" : undefined}>
        <IndexIndicatorBar indicatorControls={indicatorControls} overlay={overlay} setOverlay={setOverlay} supportsTrend={supportsTrend && (!!research || trendPhase === "ready")} />
        {extension?.controls}
      </div>}
      bottomBarAriaLabel="指数指标栏"
      dataKey={dataKey}
      hiddenIndicatorPanels={indicatorControls.hiddenIndicatorPanels}
      historyPhase={activeHistory?.phase}
      onHistoryViewport={activeHistory?.onViewport}
      mainLayerAccessory={(
        <><NineTurnLayerStatus
          showAlignmentDiagnostics={recognition.debug === 1}
          droppedMarkerCount={nineTurnChartLayer.droppedMarkerCount}
          layer={nineTurnLayer}
          onRetry={onNineTurnRetry}
        />{historical?.failedLayers.length ? (
          <div className="index-history-layer-errors">
            {historical.failedLayers.map(({ page, layer }) => (
              <div className="index-history-layer-error" role="status" key={`${page.endDate}|${layer}`}>
                <span>{layer === "nineTurn" ? "九转" : "趋势"}历史数据加载失败</span>
                <button type="button" onClick={() => activeHistory?.retryLayer(page, layer)}>重试</button>
              </div>
            ))}
          </div>
        ) : null}{research && trendPhase === "error" ? <button className="daily-wave-trend-error" onClick={onTrendRetry} type="button">趋势通道加载失败 · 重试</button> : null}</>
      )}
      mainLines={mainLines}
      mainPrimitives={mainPrimitives}
      mainPriceScalePaddingPx={research?.mainPriceScalePaddingPx}
      panelAriaLabels={{ kline: "指数K线主图", macd: "MACD(12,26,9)", volume: "成交量", kdj: "KDJ(9,3,3)" }}
      points={points}
      quantitativeStructure={indicatorControls.quantitativeStructureAvailable ? {
        ariaLabel: QUANTITATIVE_STRUCTURE_TITLE,
        valuesAt,
        primitives: xxm.macdPrimitives,
        renderHeader: (values) => <><IndexPanelHeader panel="quantitativeStructure" point={values} /><XxmLayerStatus layer={xxm} onRetry={xxm.retry} /></>,
      } : undefined}
      renderMainHeader={(point) => (
        <IndexMainHeader
          overlay={overlay}
          point={point}
          setOverlay={setOverlay}
          supportsTrend={supportsTrend && (!!research || trendPhase === "ready")}
          trendPoint={point ? trendByTime.get(String(point.time)) : undefined}
          waveLegend={extension?.legend}
        />
      )}
      renderPanelHeader={(panel, point) => <IndexPanelHeader panel={panel} point={point} />}
      renderTooltip={(point, side) => (
        <IndexTooltip point={point} side={side}>
          {structureVisible && xxm.data?.byTime.has(String(point.time)) ? (
            <><XxmSignalDetails layer={xxm} time={String(point.time)} />
              {recognition.debug === 1 ? recognition.renderXxmDetails?.(xxm, String(point.time)) : null}</>
          ) : null}
          {extension?.renderWaveDetails(point)}
        </IndexTooltip>
      )}
      timeAxisAriaLabel="指数日线底部时间轴"
      timeMode="daily"
    />
  );
}


function buildMaLines(): DetailChartLineDefinition[] {
  return [
    ["ma5", DETAIL_CHART_COLORS.brand], ["ma10", DETAIL_CHART_COLORS.blue],
    ["ma20", DETAIL_CHART_COLORS.purple], ["ma30", DETAIL_CHART_COLORS.cyan],
    ["ma60", DETAIL_CHART_COLORS.amber], ["ma90", DETAIL_CHART_COLORS.rose],
    ["ma250", DETAIL_CHART_COLORS.slate],
  ].map(([id, color]) => ({ id, color, valueOf: (point) => point.overlays[id] ?? null }));
}

function buildBollLines(): DetailChartLineDefinition[] {
  return [
    ["bollUpper", DETAIL_CHART_COLORS.brand], ["bollMiddle", DETAIL_CHART_COLORS.blue],
    ["bollLower", DETAIL_CHART_COLORS.purple],
  ].map(([id, color]) => ({ id, color, valueOf: (point) => point.overlays[id] ?? null }));
}

function IndexMainHeader({
  overlay, point, setOverlay, supportsTrend, trendPoint, waveLegend,
}: {
  overlay: IndexMainOverlay;
  point: DetailChartPoint | null;
  setOverlay: (overlay: IndexMainOverlay) => void;
  supportsTrend: boolean;
  trendPoint?: { shortUpper: number; shortLower: number; longUpper: number; longLower: number };
  waveLegend?: import("react").ReactNode;
}) {
  return <>
    <select aria-label="指数主图指标切换" className="detail-chart-overlay-select" value={overlay} onChange={(event) => setOverlay(event.target.value as IndexMainOverlay)}>
      <option value="MA">MA 均线</option>
      <option value="BOLL">BOLL 布林线</option>
      {supportsTrend ? <option value="TREND_CHANNEL">趋势通道</option> : null}
    </select>
    {point ? <MainMetrics overlay={overlay} point={point} trendPoint={trendPoint} /> : null}
    {waveLegend}
    <button className="detail-chart-gear" disabled title="指标设置暂未开通" type="button">⚙</button>
  </>;
}

function MainMetrics({ overlay, point, trendPoint }: { overlay: IndexMainOverlay; point: DetailChartPoint; trendPoint?: { shortUpper: number; shortLower: number; longUpper: number; longLower: number } }) {
  if (overlay === "TREND_CHANNEL") return <>
    <span className="metric ma5">短上:{format(pointValue(trendPoint?.shortUpper))}</span>
    <span className="metric ma10">短下:{format(pointValue(trendPoint?.shortLower))}</span>
    <span className="metric ma20">长上:{format(pointValue(trendPoint?.longUpper))}</span>
    <span className="metric ma90">长下:{format(pointValue(trendPoint?.longLower))}</span>
  </>;
  const keys = overlay === "BOLL" ? ["bollUpper", "bollMiddle", "bollLower"] : ["ma5", "ma10", "ma20", "ma30", "ma60", "ma90", "ma250"];
  return <>{keys.map((key) => <span className={`metric ${key.replace("bollUpper", "ma5").replace("bollMiddle", "ma10").replace("bollLower", "ma20")}`} key={key}>{key.toUpperCase()}:{format(point.overlays[key] ?? null)}</span>)}</>;
}

function IndexPanelHeader({ panel, point }: (
  | { panel: Exclude<DetailChartPanelKey, "kline">; point: DetailChartPoint | null }
  | { panel: "quantitativeStructure"; point: DetailChartMacdValues | null }
)) {
  const title = panel === "quantitativeStructure" ? QUANTITATIVE_STRUCTURE_TITLE
    : panel === "macd" ? "MACD(12,26,9)" : panel === "volume" ? "成交量" : "KDJ(9,3,3)";
  const values: Array<{ display?: string; label: string; value: number | null }> =
    panel === "quantitativeStructure" || (panel === "macd" && point)
    ? [{ label: "MACD", value: point?.macd ?? null }, { label: "DIF", value: point?.dif ?? null }, { label: "DEA", value: point?.dea ?? null }]
    : !point ? []
    : panel === "volume"
      ? [{ display: point.volumeDisplay ?? "--", label: "总量", value: point.volume }]
      : [{ label: "K", value: point.k }, { label: "D", value: point.d }, { label: "J", value: point.j }];
  return <><strong>{title}</strong>{values.map(({ display, label, value }) => {
    return <span className={`metric ${directionClass(resolveDirection(value))}`} key={label}>{label}:{display ?? format(value)}</span>;
  })}<button className="detail-chart-gear" disabled title="指标设置暂未开通" type="button">⚙</button></>;
}

function IndexIndicatorBar({ indicatorControls, overlay, setOverlay, supportsTrend }: {
  indicatorControls: DetailChartIndicatorControls;
  overlay: IndexMainOverlay;
  setOverlay: (overlay: IndexMainOverlay) => void;
  supportsTrend: boolean;
}) {
  return <div className="detail-chart-indicator-tabs">
    <DetailChartIndicatorToggle panel="volume" indicatorControls={indicatorControls} />
    <button className="detail-chart-indicator-tab" disabled type="button">成交额</button>
    <DetailChartIndicatorToggle panel="macd" indicatorControls={indicatorControls} />
    <DetailChartIndicatorToggle panel="kdj" indicatorControls={indicatorControls} />
    <DetailChartIndicatorToggle panel="quantitativeStructure" indicatorControls={indicatorControls}
      mode={indicatorControls.quantitativeStructureAvailable ? "available" : "disabled"} />
    <button className={`detail-chart-indicator-tab ${overlay === "MA" ? "active" : ""}`} type="button" onClick={() => setOverlay("MA")}>均线</button>
    <button className={`detail-chart-indicator-tab ${overlay === "BOLL" ? "active" : ""}`} type="button" onClick={() => setOverlay("BOLL")}>BOLL</button>
    {supportsTrend ? <button className={`detail-chart-indicator-tab ${overlay === "TREND_CHANNEL" ? "active" : ""}`} type="button" onClick={() => setOverlay("TREND_CHANNEL")}>趋势通道</button> : null}
  </div>;
}

function IndexTooltip({ point, side, children }: { point: DetailChartPoint; side: DetailChartTooltipSide; children: ReactNode }) {
  const rows = [
    ["时间", point.fullDate.replaceAll("-", ""), "secondary"],
    ["开盘", format(point.open), directionClass(compare(point.open, point.preClose))],
    ["收盘", format(point.close), directionClass(compare(point.close, point.preClose))],
    ["最高", format(point.high), directionClass(compare(point.high, point.preClose))],
    ["最低", format(point.low), directionClass(compare(point.low, point.preClose))],
    ["涨幅", isFiniteChartNumber(point.changePct) ? `${point.changePct.toFixed(2)}%` : "--", directionClass(resolveDirection(point.changePct))],
    ["振幅", isFiniteChartNumber(point.amplitude) ? `${point.amplitude.toFixed(2)}%` : "--", "secondary"],
    ["成交量", point.volumeDisplay ?? "--", "secondary"],
    ["成交额", formatCompact(point.amount, ""), "secondary"],
  ];
  return <div className={`detail-chart-tooltip ${side}`}><div className="detail-chart-tooltip-grid">{rows.map(([label, value, tone]) => <div className="detail-chart-tooltip-row" key={label}><span>{label}</span><b className={tone}>{value}</b></div>)}</div>{children}</div>;
}

function pointValue(value: number | undefined): number | null { return Number.isFinite(value) ? value ?? null : null; }
function format(value: number | null): string { return isFiniteChartNumber(value) ? value.toFixed(2) : "--"; }
function formatCompact(value: number | null, unit: string): string {
  if (!isFiniteChartNumber(value)) return "--";
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿${unit}`;
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(2)}万${unit}`;
  return `${value.toFixed(2)}${unit}`;
}
function compare(value: number | null, base: number | null): MarketDirection {
  if (!isFiniteChartNumber(value) || !isFiniteChartNumber(base)) return "UNKNOWN";
  return value > base ? "UP" : value < base ? "DOWN" : "FLAT";
}
function resolveDirection(value: number | null): MarketDirection {
  if (!isFiniteChartNumber(value)) return "UNKNOWN";
  return value > 0 ? "UP" : value < 0 ? "DOWN" : "FLAT";
}
