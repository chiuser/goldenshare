import { useMemo, useState } from "react";
import type { UTCTimestamp } from "lightweight-charts";

import { DetailChartWorkspace } from "../../../shared/charts/detail-workspace/DetailChartWorkspace";
import { DETAIL_CHART_COLORS, isFiniteChartNumber } from "../../../shared/charts/detail-workspace/detailChartSeries";
import type {
  DetailChartLineDefinition,
  DetailChartPanelKey,
  DetailChartPoint,
  DetailChartTooltipSide,
} from "../../../shared/charts/detail-workspace/detailChartTypes";
import { formatMinuteTradeTime } from "../../../shared/charts/detail-workspace/detailChartFormatters";
import { directionClass } from "../../../shared/lib/marketDirection";
import type { MarketDirection } from "../../../shared/model/market";
import type {
  IndexMainOverlay,
  IndexMinuteChartViewModel,
  IndexMinuteSeriesState,
} from "../model/indexDetailTypes";

interface IndexMinuteChartWorkspaceProps extends IndexMinuteSeriesState {
  onRetry: () => void;
}

export function IndexMinuteChartWorkspace({ data, errorMessage, onRetry, phase }: IndexMinuteChartWorkspaceProps) {
  if (!data || data.points.length === 0) {
    return <IndexMinuteModuleState errorMessage={errorMessage} onRetry={onRetry} phase={phase} />;
  }
  return <LoadedIndexMinuteChart data={data} message={errorMessage} phase={phase} />;
}

function LoadedIndexMinuteChart({
  data,
  message,
  phase,
}: {
  data: IndexMinuteChartViewModel;
  message: string;
  phase: IndexMinuteSeriesState["phase"];
}) {
  const [overlay, setOverlay] = useState<Exclude<IndexMainOverlay, "TREND_CHANNEL">>("MA");
  const points = useMemo(() => data.points.map(toDetailChartPoint), [data.points]);
  const mainLines = useMemo(() => overlay === "MA" ? buildMaLines() : buildBollLines(), [overlay]);

  return (
    <DetailChartWorkspace
      ariaLabel="指数分钟图表区"
      bottomBar={<IndexMinuteIndicatorBar message={message} overlay={overlay} phase={phase} setOverlay={setOverlay} />}
      bottomBarAriaLabel="指数分钟指标栏"
      dataKey={`index:${data.tsCode}:m${data.freq}`}
      mainLines={mainLines}
      panelAriaLabels={{ kline: "指数分钟K线主图", macd: "分钟 MACD(12,26,9)", volume: "分钟成交量", kdj: "分钟 KDJ(9,3,3)" }}
      points={points}
      renderMainHeader={(point) => <IndexMinuteMainHeader overlay={overlay} point={point} setOverlay={setOverlay} />}
      renderPanelHeader={(panel, point) => <IndexMinutePanelHeader panel={panel} point={point} />}
      renderTooltip={(point, side) => <IndexMinuteTooltip point={point} side={side} />}
      timeAxisAriaLabel="指数分钟底部时间轴"
      timeMode="minute"
    />
  );
}

function toDetailChartPoint(point: IndexMinuteChartViewModel["points"][number]): DetailChartPoint {
  return {
    ...point,
    time: point.time as UTCTimestamp,
    turnoverRate: null,
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

function IndexMinuteMainHeader({
  overlay,
  point,
  setOverlay,
}: {
  overlay: Exclude<IndexMainOverlay, "TREND_CHANNEL">;
  point: DetailChartPoint | null;
  setOverlay: (overlay: Exclude<IndexMainOverlay, "TREND_CHANNEL">) => void;
}) {
  const keys = overlay === "MA"
    ? ["ma5", "ma10", "ma20", "ma30", "ma60", "ma90", "ma250"]
    : ["bollUpper", "bollMiddle", "bollLower"];
  return <>
    <select
      aria-label="指数分钟主图指标切换"
      className="detail-chart-overlay-select"
      value={overlay}
      onChange={(event) => setOverlay(event.target.value as Exclude<IndexMainOverlay, "TREND_CHANNEL">)}
    >
      <option value="MA">MA 均线</option>
      <option value="BOLL">BOLL 布林线</option>
    </select>
    {point ? keys.map((key) => (
      <span className={`metric ${metricClass(key)}`} key={key}>{metricLabel(key)}:{format(point.overlays[key] ?? null)}</span>
    )) : null}
  </>;
}

function IndexMinutePanelHeader({
  panel,
  point,
}: {
  panel: Exclude<DetailChartPanelKey, "kline">;
  point: DetailChartPoint | null;
}) {
  const title = panel === "macd" ? "MACD(12,26,9)" : panel === "volume" ? "成交量" : "KDJ(9,3,3)";
  const values = !point ? [] : panel === "macd"
    ? [["MACD", point.macd], ["DIF", point.dif], ["DEA", point.dea]]
    : panel === "volume" ? [["总量", point.volume]] : [["K", point.k], ["D", point.d], ["J", point.j]];
  return <><strong>{title}</strong>{values.map(([label, raw]) => {
    const value = typeof raw === "number" ? raw : null;
    return <span className={`metric ${directionClass(resolveDirection(value))}`} key={String(label)}>{label}:{format(value)}</span>;
  })}</>;
}

function IndexMinuteIndicatorBar({
  message,
  overlay,
  phase,
  setOverlay,
}: {
  message: string;
  overlay: Exclude<IndexMainOverlay, "TREND_CHANNEL">;
  phase: IndexMinuteSeriesState["phase"];
  setOverlay: (overlay: Exclude<IndexMainOverlay, "TREND_CHANNEL">) => void;
}) {
  return <div className="detail-chart-indicator-tabs">
    <button className={`detail-chart-indicator-tab ${overlay === "MA" ? "active" : ""}`} type="button" onClick={() => setOverlay("MA")}>均线</button>
    <button className={`detail-chart-indicator-tab ${overlay === "BOLL" ? "active" : ""}`} type="button" onClick={() => setOverlay("BOLL")}>BOLL</button>
    {phase === "delayed" || phase === "partial" ? <span className="index-minute-status-message">{message}</span> : null}
  </div>;
}

function IndexMinuteTooltip({ point, side }: { point: DetailChartPoint; side: DetailChartTooltipSide }) {
  const rows = [
    ["时间", formatMinuteTradeTime(point.fullDate), "secondary"],
    ["开盘", format(point.open), "flat"],
    ["收盘", format(point.close), directionClass(compare(point.close, point.open))],
    ["最高", format(point.high), directionClass(compare(point.high, point.open))],
    ["最低", format(point.low), directionClass(compare(point.low, point.open))],
    ["成交量", formatMinuteVolume(point.volume), "secondary"],
    ["成交额", formatMinuteAmount(point.amount), "secondary"],
  ];
  return <div aria-label="指数分钟K线数据提示" className={`detail-chart-tooltip ${side}`}><div className="detail-chart-tooltip-grid">
    {rows.map(([label, value, tone]) => <div className="detail-chart-tooltip-row" key={label}><span>{label}</span><b className={tone}>{value}</b></div>)}
  </div></div>;
}

function IndexMinuteModuleState({
  errorMessage,
  onRetry,
  phase,
}: {
  errorMessage: string;
  onRetry: () => void;
  phase: IndexMinuteSeriesState["phase"];
}) {
  const loading = phase === "loading" || phase === "idle";
  const title = loading ? "正在加载指数分钟数据" : phase === "empty" ? "暂无指数分钟数据" : "指数分钟数据加载失败";
  const message = loading ? "正在读取正式 Silver 分钟 K 线" : errorMessage || "请稍后重试。";
  return <section className="detail-chart-workspace index-minute-module-state" aria-label="指数分钟图表区">
    <div role="status"><strong>{title}</strong><span>{message}</span>{phase === "error" ? <button type="button" onClick={onRetry}>重新加载</button> : null}</div>
    <div aria-hidden="true" className="detail-chart-indicator-bar" />
  </section>;
}

function metricLabel(key: string): string {
  if (key === "bollUpper") return "UPPER";
  if (key === "bollMiddle") return "MID";
  if (key === "bollLower") return "LOWER";
  return key.toUpperCase();
}
function metricClass(key: string): string {
  return key.replace("bollUpper", "ma5").replace("bollMiddle", "ma10").replace("bollLower", "ma20");
}
function format(value: number | null): string { return isFiniteChartNumber(value) ? value.toFixed(2) : "--"; }
function resolveDirection(value: number | null): MarketDirection {
  if (!isFiniteChartNumber(value)) return "UNKNOWN";
  return value > 0 ? "UP" : value < 0 ? "DOWN" : "FLAT";
}
function compare(value: number | null, base: number | null): MarketDirection {
  if (!isFiniteChartNumber(value) || !isFiniteChartNumber(base)) return "UNKNOWN";
  return value > base ? "UP" : value < base ? "DOWN" : "FLAT";
}
function formatMinuteVolume(value: number | null): string {
  if (!isFiniteChartNumber(value)) return "--";
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿股`;
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(2)}万股`;
  return `${Math.round(value)}股`;
}
function formatMinuteAmount(value: number | null): string {
  if (!isFiniteChartNumber(value)) return "--";
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿元`;
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(2)}万元`;
  return `${value.toFixed(2)}元`;
}
