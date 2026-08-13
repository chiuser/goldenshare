import { useMemo } from "react";
import type { UTCTimestamp } from "lightweight-charts";

import { useNineTurnChartLayer } from "../../nine-turn/controller/useNineTurnChartLayer";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import { NineTurnLayerStatus } from "../../nine-turn/ui/NineTurnLayerStatus";
import { DetailChartWorkspace } from "../../../shared/charts/detail-workspace/DetailChartWorkspace";
import type {
  DetailChartLineDefinition,
  DetailChartPanelKey,
  DetailChartPoint,
  DetailChartTooltipSide,
} from "../../../shared/charts/detail-workspace/detailChartTypes";
import { directionClass } from "../../../shared/lib/marketDirection";
import type { MarketDirection } from "../../../shared/model/market";
import type { StockMinuteChartPoint, StockMinuteChartViewModel } from "../api/stockMinuteViewModelAdapter";

interface StockMinuteChartWorkspaceProps {
  data: StockMinuteChartViewModel | null;
  loadState: "idle" | "loading" | "ready" | "error";
  errorMessage?: string;
  nineTurnLayer: NineTurnLayerViewModel;
  onNineTurnRetry: () => void;
}

const STOCK_MINUTE_MAIN_LINES: DetailChartLineDefinition[] = [];

export function StockMinuteChartWorkspace({
  data,
  loadState,
  errorMessage,
  nineTurnLayer,
  onNineTurnRetry,
}: StockMinuteChartWorkspaceProps) {
  const status = data ? resolveMinuteStatus(data) : loadState === "error" ? "ERROR" : loadState === "loading" ? "LOADING" : "EMPTY";
  const statusMessage = errorMessage ?? resolveMinuteStatusMessage(data, status);
  const points = useMemo(() => data?.points.map(toDetailChartPoint) ?? [], [data?.points]);
  const dataKey = `stock:${data?.tsCode ?? "pending"}:m${data?.freq ?? "pending"}`;
  const nineTurnChartLayer = useNineTurnChartLayer({
    dataKey,
    layer: nineTurnLayer,
    points,
    timeMode: "minute",
  });

  if (!data || data.points.length === 0) {
    return (
      <section className="stock-detail-chart-workbench stock-minute-chart-workbench" aria-label="分钟图表区">
        <div className="stock-minute-chart-empty" role="status">
          <strong>{statusMessage}</strong>
          <span>freq={data?.freq ?? "-"}，dataStatus={status}</span>
        </div>
      </section>
    );
  }

  return (
    <DetailChartWorkspace
      ariaLabel="分钟图表区"
      crosshairPresentation="native-axis-labels"
      dataKey={dataKey}
      mainLayerAccessory={(
        <NineTurnLayerStatus
          droppedMarkerCount={nineTurnChartLayer.droppedMarkerCount}
          layer={nineTurnLayer}
          onRetry={onNineTurnRetry}
        />
      )}
      mainLines={STOCK_MINUTE_MAIN_LINES}
      mainPrimitives={nineTurnChartLayer.mainPrimitives}
      panelAriaLabels={{
        kline: "分钟K线",
        macd: "MACD(12,26,9)",
        volume: "成交量",
        kdj: "KDJ(9,3,3)",
      }}
      points={points}
      renderMainHeader={(point) => (
        <>
          <strong>分钟K线</strong>
          {point ? <span className="metric">收盘:{formatNumber(point.close)}</span> : null}
        </>
      )}
      renderPanelHeader={(panel, point) => <StockMinutePanelHeader panel={panel} point={point} />}
      renderTooltip={(point, side) => <MinuteKlineTooltip point={point} side={side} />}
      timeAxisAriaLabel="股票分钟底部时间轴"
      timeAxisPlacement="each-pane"
      timeMode="minute"
      topRightAccessory={(
        <div className="stock-minute-chart-status" role="status">
          <span>{statusMessage}</span>
          <span>freq={data.freq}</span>
        </div>
      )}
    />
  );
}

function toDetailChartPoint(point: StockMinuteChartPoint): DetailChartPoint {
  return {
    time: point.timestamp as UTCTimestamp,
    fullDate: point.tradeTime,
    open: point.open,
    high: point.high,
    low: point.low,
    close: point.close,
    preClose: null,
    changePct: null,
    amplitude: null,
    volume: point.volume,
    amount: point.amount,
    turnoverRate: null,
    macd: point.macd,
    dif: point.macdDif,
    dea: point.macdDea,
    k: point.kdjK,
    d: point.kdjD,
    j: point.kdjJ,
    overlays: {},
  };
}

function StockMinutePanelHeader({
  panel,
  point,
}: {
  panel: Exclude<DetailChartPanelKey, "kline">;
  point: DetailChartPoint | null;
}) {
  const title = panel === "macd" ? "MACD(12,26,9)" : panel === "volume" ? "成交量" : "KDJ(9,3,3)";
  const metrics = !point
    ? []
    : panel === "macd"
      ? [["DIF", point.dif], ["DEA", point.dea], ["MACD", point.macd]]
      : panel === "volume"
        ? [["量", point.volume]]
        : [["K", point.k], ["D", point.d], ["J", point.j]];
  return (
    <>
      <strong>{title}</strong>
      {metrics.map(([label, value]) => (
        <span className="metric" key={String(label)}>{label}:{formatNullable(typeof value === "number" ? value : null)}</span>
      ))}
    </>
  );
}

function MinuteKlineTooltip({ point, side }: { point: DetailChartPoint; side: DetailChartTooltipSide }) {
  const open = point.open ?? Number.NaN;
  const rows: Array<[string, string, string]> = [
    ["时间", formatMinuteTradeTime(point.fullDate), "secondary"],
    ["开盘", formatNumber(point.open), "flat"],
    ["收盘", formatNumber(point.close), directionClass(resolveMinuteCandleDirection(point.close, open))],
    ["最高", formatNumber(point.high), directionClass(resolveMinuteCandleDirection(point.high, open))],
    ["最低", formatNumber(point.low), directionClass(resolveMinuteCandleDirection(point.low, open))],
    ["成交量", formatMinuteTooltipVolume(point.volume), "secondary"],
    ["成交额", formatMinuteTooltipAmount(point.amount), "secondary"],
  ];
  return (
    <div aria-label="分钟K线数据提示" className={`kline-tooltip ${side}`}>
      <div className="tooltip-grid">
        {rows.map(([label, value, tone]) => (
          <div className="tooltip-row" key={label}>
            <span>{label}</span>
            <b className={tone}>{value}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

function resolveMinuteStatus(data: StockMinuteChartViewModel): string {
  if (data.dataStatus.status === "DELAYED" || data.indicatorStatus.status === "DELAYED") return "DELAYED";
  if (data.dataStatus.status === "ERROR" || data.indicatorStatus.status === "ERROR") return "ERROR";
  return data.dataStatus.status;
}

function resolveMinuteStatusMessage(data: StockMinuteChartViewModel | null, status: string): string {
  if (!data) return statusMessageFor(status);
  if (data.indicatorStatus.status !== "READY" && data.indicatorStatus.message) return data.indicatorStatus.message;
  if (data.dataStatus.status !== "READY" && data.dataStatus.message) return data.dataStatus.message;
  return statusMessageFor(status);
}

function statusMessageFor(status: string): string {
  if (status === "LOADING") return "正在加载分钟数据";
  if (status === "DELAYED") return "分钟数据尚未覆盖页面期望交易日";
  if (status === "ERROR") return "分钟数据加载失败";
  return "暂无分钟数据";
}

function formatMinuteTradeTime(value: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value);
  return match ? `${match[1]?.replaceAll("-", "")} ${match[2]}` : value;
}

function resolveMinuteCandleDirection(value: number | null, open: number): MarketDirection {
  if (value === null || !Number.isFinite(value) || !Number.isFinite(open)) return "UNKNOWN";
  if (value > open) return "UP";
  if (value < open) return "DOWN";
  return "FLAT";
}

function formatMinuteTooltipVolume(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "--";
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿股`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(2)}万股`;
  return `${Math.round(value)}股`;
}

function formatMinuteTooltipAmount(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "--";
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿元`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(2)}万元`;
  return `${value.toFixed(2)}元`;
}

function formatNumber(value: number | null): string {
  return value !== null && Number.isFinite(value) ? value.toFixed(2) : "--";
}

function formatNullable(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "--" : value.toFixed(2);
}
