import { useEffect, useMemo, useState } from "react";

import { useNineTurnChartLayer } from "../../nine-turn/controller/useNineTurnChartLayer";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import { NineTurnLayerStatus } from "../../nine-turn/ui/NineTurnLayerStatus";
import { DetailChartWorkspace } from "../../../shared/charts/detail-workspace/DetailChartWorkspace";
import { DETAIL_CHART_COLORS, isFiniteChartNumber } from "../../../shared/charts/detail-workspace/detailChartSeries";
import type {
  DetailChartLineDefinition,
  DetailChartPanelKey,
  DetailChartPoint,
  DetailChartTooltipSide,
} from "../../../shared/charts/detail-workspace/detailChartTypes";
import { directionClass } from "../../../shared/lib/marketDirection";
import type { MarketDirection } from "../../../shared/model/market";
import { TrendChannelPanePrimitive } from "../../../shared/charts/trend-channel/TrendChannelPanePrimitive";
import { buildTrendChannelLines } from "../../../shared/charts/trend-channel/trendChannelGeometry";
import type {
  IndexCandlePoint,
  IndexDetailViewModel,
  IndexMainOverlay,
  TrendChannelViewModel,
} from "../model/indexDetailTypes";

interface IndexChartWorkspaceProps {
  nineTurnLayer: NineTurnLayerViewModel;
  onNineTurnRetry: () => void;
  trend: TrendChannelViewModel | null;
  trendPhase: "unavailable" | "loading" | "ready" | "error";
  viewModel: IndexDetailViewModel;
}

export function IndexChartWorkspace({ nineTurnLayer, onNineTurnRetry, trend, trendPhase, viewModel }: IndexChartWorkspaceProps) {
  const supportsTrend = viewModel.capabilities.supportsTrendChannel && viewModel.identity.tsCode === "000001.SH";
  const [overlay, setOverlay] = useState<IndexMainOverlay>(supportsTrend && trend ? "TREND_CHANNEL" : "MA");
  useEffect(() => {
    setOverlay(supportsTrend && trend ? "TREND_CHANNEL" : "MA");
  }, [supportsTrend, trend, viewModel.identity.tsCode]);

  const points = useMemo(() => viewModel.chart.candles.map(toDetailChartPoint), [viewModel.chart.candles]);
  const dataKey = `index:${viewModel.identity.tsCode}:day`;
  const nineTurnChartLayer = useNineTurnChartLayer({ dataKey, layer: nineTurnLayer, points, timeMode: "daily" });
  const trendByTime = useMemo(() => new Map((trend?.points ?? []).map((point) => [point.time, point])), [trend]);
  const mainLines = useMemo(() => overlay === "MA" ? buildMaLines() : overlay === "BOLL" ? buildBollLines() : [], [overlay]);
  const trendPrimitives = useMemo(() => {
    if (overlay !== "TREND_CHANNEL" || !trend) return [];
    const lines = buildTrendChannelLines(trend.points, points.map((point) => String(point.time)));
    return [new TrendChannelPanePrimitive(lines)];
  }, [overlay, points, trend]);
  const mainPrimitives = useMemo(
    () => [...trendPrimitives, ...nineTurnChartLayer.mainPrimitives],
    [nineTurnChartLayer.mainPrimitives, trendPrimitives],
  );

  return (
    <DetailChartWorkspace
      ariaLabel="指数日线图表区"
      bottomBar={<IndexIndicatorBar overlay={overlay} setOverlay={setOverlay} supportsTrend={supportsTrend && trendPhase === "ready"} />}
      bottomBarAriaLabel="指数指标栏"
      dataKey={dataKey}
      mainLayerAccessory={(
        <NineTurnLayerStatus
          droppedMarkerCount={nineTurnChartLayer.droppedMarkerCount}
          layer={nineTurnLayer}
          onRetry={onNineTurnRetry}
        />
      )}
      mainLines={mainLines}
      mainPrimitives={mainPrimitives}
      panelAriaLabels={{ kline: "指数K线主图", macd: "MACD(12,26,9)", volume: "成交量", kdj: "KDJ(9,3,3)" }}
      points={points}
      renderMainHeader={(point) => (
        <IndexMainHeader
          overlay={overlay}
          point={point}
          setOverlay={setOverlay}
          supportsTrend={supportsTrend && trendPhase === "ready"}
          trendPoint={point ? trendByTime.get(String(point.time)) : undefined}
        />
      )}
      renderPanelHeader={(panel, point) => <IndexPanelHeader panel={panel} point={point} />}
      renderTooltip={(point, side) => <IndexTooltip point={point} side={side} />}
      timeAxisAriaLabel="指数日线底部时间轴"
      timeMode="daily"
    />
  );
}

function toDetailChartPoint(point: IndexCandlePoint): DetailChartPoint {
  return {
    time: point.time,
    fullDate: point.fullDate,
    open: point.open,
    high: point.high,
    low: point.low,
    close: point.close,
    preClose: point.preClose,
    changePct: point.changePct,
    amplitude: point.amplitude,
    volume: point.volume,
    volumeDisplay: point.volumeDisplay,
    amount: point.amount,
    turnoverRate: null,
    macd: point.macd,
    dif: point.dif,
    dea: point.dea,
    k: point.k,
    d: point.d,
    j: point.j,
    overlays: {
      ma5: point.ma5, ma10: point.ma10, ma20: point.ma20, ma30: point.ma30,
      ma60: point.ma60, ma90: point.ma90, ma250: point.ma250,
      bollUpper: point.bollUpper, bollMiddle: point.bollMiddle, bollLower: point.bollLower,
    },
  };
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
  overlay, point, setOverlay, supportsTrend, trendPoint,
}: {
  overlay: IndexMainOverlay;
  point: DetailChartPoint | null;
  setOverlay: (overlay: IndexMainOverlay) => void;
  supportsTrend: boolean;
  trendPoint?: { shortUpper: number; shortLower: number; longUpper: number; longLower: number };
}) {
  return <>
    <select aria-label="指数主图指标切换" className="detail-chart-overlay-select" value={overlay} onChange={(event) => setOverlay(event.target.value as IndexMainOverlay)}>
      <option value="MA">MA 均线</option>
      <option value="BOLL">BOLL 布林线</option>
      {supportsTrend ? <option value="TREND_CHANNEL">趋势通道</option> : null}
    </select>
    {point ? <MainMetrics overlay={overlay} point={point} trendPoint={trendPoint} /> : null}
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

function IndexPanelHeader({ panel, point }: { panel: Exclude<DetailChartPanelKey, "kline">; point: DetailChartPoint | null }) {
  const title = panel === "macd" ? "MACD(12,26,9)" : panel === "volume" ? "成交量" : "KDJ(9,3,3)";
  const values: Array<{ display?: string; label: string; value: number | null }> = !point ? [] : panel === "macd"
    ? [{ label: "MACD", value: point.macd }, { label: "DIF", value: point.dif }, { label: "DEA", value: point.dea }]
    : panel === "volume"
      ? [{ display: point.volumeDisplay ?? "--", label: "总量", value: point.volume }]
      : [{ label: "K", value: point.k }, { label: "D", value: point.d }, { label: "J", value: point.j }];
  return <><strong>{title}</strong>{values.map(({ display, label, value }) => {
    return <span className={`metric ${directionClass(resolveDirection(value))}`} key={label}>{label}:{display ?? format(value)}</span>;
  })}<button className="detail-chart-gear" disabled title="指标设置暂未开通" type="button">⚙</button></>;
}

function IndexIndicatorBar({ overlay, setOverlay, supportsTrend }: { overlay: IndexMainOverlay; setOverlay: (overlay: IndexMainOverlay) => void; supportsTrend: boolean }) {
  return <div className="detail-chart-indicator-tabs">
    {["VOL", "成交额", "MACD", "KDJ"].map((label) => <button className="detail-chart-indicator-tab" disabled key={label} type="button">{label}</button>)}
    <button className={`detail-chart-indicator-tab ${overlay === "MA" ? "active" : ""}`} type="button" onClick={() => setOverlay("MA")}>均线</button>
    <button className={`detail-chart-indicator-tab ${overlay === "BOLL" ? "active" : ""}`} type="button" onClick={() => setOverlay("BOLL")}>BOLL</button>
    {supportsTrend ? <button className={`detail-chart-indicator-tab ${overlay === "TREND_CHANNEL" ? "active" : ""}`} type="button" onClick={() => setOverlay("TREND_CHANNEL")}>趋势通道</button> : null}
  </div>;
}

function IndexTooltip({ point, side }: { point: DetailChartPoint; side: DetailChartTooltipSide }) {
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
  return <div className={`detail-chart-tooltip ${side}`}><div className="detail-chart-tooltip-grid">{rows.map(([label, value, tone]) => <div className="detail-chart-tooltip-row" key={label}><span>{label}</span><b className={tone}>{value}</b></div>)}</div></div>;
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
