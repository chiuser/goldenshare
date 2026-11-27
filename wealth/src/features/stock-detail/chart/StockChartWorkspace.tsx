import { Fragment, useEffect, useMemo, useState } from "react";

import { useNineTurnChartLayer } from "../../nine-turn/controller/useNineTurnChartLayer";
import type { NineTurnDisplayControl } from "../../nine-turn/controller/useNineTurnDisplayControl";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import { NineTurnIndicatorToggle } from "../../nine-turn/ui/NineTurnIndicatorToggle";
import { NineTurnLayerStatus } from "../../nine-turn/ui/NineTurnLayerStatus";
import { DetailChartIndicatorToggle } from "../../../shared/charts/detail-workspace/DetailChartIndicatorToggle";
import { DetailChartWorkspace } from "../../../shared/charts/detail-workspace/DetailChartWorkspace";
import { DETAIL_CHART_COLORS, isFiniteChartNumber } from "../../../shared/charts/detail-workspace/detailChartSeries";
import type {
  DetailChartIndicatorControls,
  DetailChartIndicatorPanelKey,
  DetailChartLineDefinition,
  DetailChartPanelKey,
  DetailChartPoint,
  DetailChartTooltipSide,
} from "../../../shared/charts/detail-workspace/detailChartTypes";
import { directionClass } from "../../../shared/lib/marketDirection";
import type { MarketDirection } from "../../../shared/model/market";
import { TrendChannelPanePrimitive } from "../../../shared/charts/trend-channel/TrendChannelPanePrimitive";
import { buildTrendChannelLines } from "../../../shared/charts/trend-channel/trendChannelGeometry";
import { buildStockDailyNineTurnLayer } from "../api/stockDetailViewModelAdapter";
import type { TrendChannelPoint } from "../../../shared/charts/trend-channel/trendChannelGeometry";
import type { StockDailyHistory } from "../controller/useStockDailyHistory";
import type { DetailChartHistoryViewport } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type {
  StockCandlePoint,
  StockIndicatorTab,
  StockMainOverlay,
} from "../model/stockDetailTypes";

const EMPTY_TREND_PRIMITIVES: TrendChannelPanePrimitive[] = [];

interface StockChartWorkspaceProps {
  candles: StockCandlePoint[];
  history?: StockDailyHistory;
  indicatorControls: DetailChartIndicatorControls;
  indicatorTabs: StockIndicatorTab[];
  nineTurnControl: NineTurnDisplayControl;
  nineTurnLayer: NineTurnLayerViewModel;
  onAction: (message: string) => void;
  onOpenPriceTarget?: (trigger: HTMLButtonElement) => void;
  supportsTrendChannel: boolean;
  initialTrendPoints: readonly TrendChannelPoint[];
  tsCode: string;
  period?: "day" | "week" | "month";
  tradeDate?: string;
  periodNote?: string | null;
  periodHistory?: {
    phase: "idle" | "loading" | "error";
    onViewport: (viewport: DetailChartHistoryViewport) => void;
    retry: () => void;
  };
}

export function StockChartWorkspace({
  candles,
  history,
  indicatorControls,
  indicatorTabs,
  nineTurnControl,
  nineTurnLayer: initialNineTurn,
  onAction,
  onOpenPriceTarget,
  supportsTrendChannel,
  initialTrendPoints,
  tsCode,
  period = "day",
  tradeDate,
  periodNote,
  periodHistory,
}: StockChartWorkspaceProps) {
  const [overlay, setOverlay] = useState<StockMainOverlay | null>("MA");
  useEffect(() => {
    setOverlay("MA");
  }, [tsCode]);
  useEffect(() => {
    if (!supportsTrendChannel && overlay === "TREND_CHANNEL") setOverlay("MA");
  }, [overlay, supportsTrendChannel]);
  const historical = history?.visible;
  const chartCandles = historical?.candles ?? candles;
  const points = useMemo(() => chartCandles.map(toDetailChartPoint), [chartCandles]);
  const pages = historical?.pages;
  const initialDates = useMemo(() => new Set(candles.map(candle => candle.fullDate)), [candles]);
  const nineTurnLayer = useMemo(() => {
    if (!pages?.length) return initialNineTurn;
    return buildStockDailyNineTurnLayer([
      ...pages.flatMap(page => page.nineTurnMarkers.filter(marker => page.dates.has(marker.tradeDate))),
      ...initialNineTurn.markers.filter(marker => initialDates.has(marker.tradeDate)),
    ]);
  }, [initialDates, initialNineTurn, pages]);
  const trendPoints = useMemo(() => {
    const initial = [...initialTrendPoints];
    if (!pages?.length) return initial;
    return [
      ...pages.flatMap(page => page.trendPoints),
      ...initial.filter(point => initialDates.has(point.time)),
    ];
  }, [initialDates, pages, initialTrendPoints]);
  const mainLines = useMemo<DetailChartLineDefinition[]>(
    () => overlay === "MA" ? buildMaLines() : overlay === "BOLL" ? buildBollLines() : [],
    [overlay],
  );
  const dataKey = period === "day" ? `stock:${tsCode}:day` : `stock:${tsCode}:${period}:${tradeDate}`;
  const nineTurnChartLayer = useNineTurnChartLayer({
    dataKey,
    layer: nineTurnLayer,
    points,
    timeMode: "daily",
    visible: nineTurnControl.visible,
  });
  const trendByTime = useMemo(
    () => new Map(trendPoints.map((point) => [point.time, point])),
    [trendPoints],
  );
  const trendPrimitives = useMemo(() => {
    if (overlay !== "TREND_CHANNEL" || trendPoints.length === 0) return EMPTY_TREND_PRIMITIVES;
    const lines = buildTrendChannelLines(
      trendPoints,
      points.map((point) => String(point.time)),
    );
    return [new TrendChannelPanePrimitive(lines)];
  }, [overlay, points, trendPoints]);
  const mainPrimitives = useMemo(
    () => [...trendPrimitives, ...nineTurnChartLayer.mainPrimitives],
    [nineTurnChartLayer.mainPrimitives, trendPrimitives],
  );
  const changeOverlay = (nextOverlay: StockMainOverlay | null) => {
    setOverlay(nextOverlay);
  };

  return (
    <DetailChartWorkspace
      ariaLabel="左侧图表区"
      bottomBar={(
        <StockIndicatorBar
          indicatorControls={indicatorControls}
          indicatorTabs={indicatorTabs}
          nineTurnControl={nineTurnControl}
          onOpenPriceTarget={period === "day" && points.length > 0 ? onOpenPriceTarget : undefined}
          onOverlayChange={changeOverlay}
          overlay={overlay}
          supportsTrendChannel={supportsTrendChannel}
        />
      )}
      bottomBarAriaLabel="底部指标栏"
      dataKey={dataKey}
      hiddenIndicatorPanels={indicatorControls.hiddenIndicatorPanels}
      historyPhase={periodHistory?.phase ?? (history?.active ? historical?.phase ?? "idle" : undefined)}
      onHistoryViewport={periodHistory?.onViewport ?? (history?.active ? history.onViewport : undefined)}
      mainLayerAccessory={(
        <>{periodNote ? <div className="stock-history-layer-errors" role="status">{periodNote}</div> : null}
        {periodHistory?.phase === "error" ? (
          <div className="stock-history-layer-errors" role="status">
            <span>周线历史加载失败</span><button type="button" onClick={periodHistory.retry}>重试</button>
          </div>
        ) : null}<NineTurnLayerStatus
          droppedMarkerCount={nineTurnChartLayer.droppedMarkerCount}
          layer={nineTurnLayer}
        /></>
      )}
      mainLines={mainLines}
      mainPrimitives={mainPrimitives}
      panelAriaLabels={{
        kline: "K线主图",
        macd: "MACD(12,26,9)",
        volume: "成交量",
        kdj: "KDJ(9,3,3)",
      }}
      points={points}
      renderMainHeader={(point) => (
        <StockMainChartHeader
          onAction={onAction}
          overlay={overlay}
          point={point}
          trendPoint={point ? trendByTime.get(String(point.time)) : undefined}
        />
      )}
      renderPanelHeader={(panel, point) => <StockIndicatorPanelHeader panel={panel} point={point} />}
      renderTooltip={(point, side) => <StockKlineTooltip point={point} side={side} daily={period === "day"} />}
      timeAxisAriaLabel={period === "week" ? "周线底部时间轴" : period === "month" ? "月线底部时间轴" : "日线底部时间轴"}
      timeMode="daily"
    />
  );
}

function toDetailChartPoint(point: StockCandlePoint): DetailChartPoint {
  const detailPoint: DetailChartPoint = {
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
    turnoverRate: point.turnoverRate,
    macd: point.macd,
    dif: point.dif,
    dea: point.dea,
    k: point.k,
    d: point.d,
    j: point.j,
    overlays: {
      ma5: point.ma5,
      ma10: point.ma10,
      ma20: point.ma20,
      ma30: point.ma30,
      ma60: point.ma60,
      ma90: point.ma90,
      ma250: point.ma250,
      bollUpper: point.bollUpper,
      bollMiddle: point.bollMiddle,
      bollLower: point.bollLower,
    },
  };
  return detailPoint;
}

function buildMaLines(): DetailChartLineDefinition[] {
  return [
    { id: "ma5", color: DETAIL_CHART_COLORS.brand, valueOf: stockFactor("ma5") },
    { id: "ma10", color: DETAIL_CHART_COLORS.blue, valueOf: stockFactor("ma10") },
    { id: "ma20", color: DETAIL_CHART_COLORS.purple, valueOf: stockFactor("ma20") },
    { id: "ma30", color: DETAIL_CHART_COLORS.cyan, valueOf: stockFactor("ma30") },
    { id: "ma60", color: DETAIL_CHART_COLORS.amber, valueOf: stockFactor("ma60") },
    { id: "ma90", color: DETAIL_CHART_COLORS.rose, valueOf: stockFactor("ma90") },
    { id: "ma250", color: DETAIL_CHART_COLORS.slate, valueOf: stockFactor("ma250") },
  ];
}

function buildBollLines(): DetailChartLineDefinition[] {
  return [
    { id: "bollUpper", color: DETAIL_CHART_COLORS.brand, valueOf: stockFactor("bollUpper") },
    { id: "bollMiddle", color: DETAIL_CHART_COLORS.blue, valueOf: stockFactor("bollMiddle") },
    { id: "bollLower", color: DETAIL_CHART_COLORS.purple, valueOf: stockFactor("bollLower") },
  ];
}

function stockFactor(
  key: "ma5" | "ma10" | "ma20" | "ma30" | "ma60" | "ma90" | "ma250" | "bollUpper" | "bollMiddle" | "bollLower",
) {
  return (point: DetailChartPoint): number | null => readStockFactor(point, key);
}

function StockMainChartHeader({
  onAction,
  overlay,
  point,
  trendPoint,
}: {
  onAction: (message: string) => void;
  overlay: StockMainOverlay | null;
  point: DetailChartPoint | null;
  trendPoint?: { shortUpper: number; shortLower: number; longUpper: number; longLower: number };
}) {
  return (
    <>
      {point && overlay !== null ? <StockKlineMetrics point={point} overlay={overlay} trendPoint={trendPoint} /> : null}
      <button
        className="detail-chart-gear"
        title="指标设置"
        type="button"
        onClick={() => onAction("指标设置暂未开通")}
      >
        ⚙
      </button>
    </>
  );
}

function StockKlineMetrics({
  point,
  overlay,
  trendPoint,
}: {
  point: DetailChartPoint;
  overlay: StockMainOverlay;
  trendPoint?: { shortUpper: number; shortLower: number; longUpper: number; longLower: number };
}) {
  if (overlay === "TREND_CHANNEL") {
    return (
      <>
        <span className="metric ma5">短上:{formatMetric(finiteTrendValue(trendPoint?.shortUpper))}</span>
        <span className="metric ma10">短下:{formatMetric(finiteTrendValue(trendPoint?.shortLower))}</span>
        <span className="metric ma20">长上:{formatMetric(finiteTrendValue(trendPoint?.longUpper))}</span>
        <span className="metric ma90">长下:{formatMetric(finiteTrendValue(trendPoint?.longLower))}</span>
      </>
    );
  }
  if (overlay === "BOLL") {
    return (
      <>
        <span className="metric ma5">UPPER:{formatMetric(readStockFactor(point, "bollUpper"))}</span>
        <span className="metric ma10">MID:{formatMetric(readStockFactor(point, "bollMiddle"))}</span>
        <span className="metric ma20">LOWER:{formatMetric(readStockFactor(point, "bollLower"))}</span>
      </>
    );
  }
  return (
    <>
      <span className="metric ma5">MA5:{formatMetric(readStockFactor(point, "ma5"))}</span>
      <span className="metric ma10">MA10:{formatMetric(readStockFactor(point, "ma10"))}</span>
      <span className="metric ma20">MA20:{formatMetric(readStockFactor(point, "ma20"))}</span>
      <span className="metric ma30">MA30:{formatMetric(readStockFactor(point, "ma30"))}</span>
      <span className="metric ma60">MA60:{formatMetric(readStockFactor(point, "ma60"))}</span>
      <span className="metric ma90">MA90:{formatMetric(readStockFactor(point, "ma90"))}</span>
      <span className="metric ma250">MA250:{formatMetric(readStockFactor(point, "ma250"))}</span>
    </>
  );
}

function StockIndicatorPanelHeader({
  panel,
  point,
}: {
  panel: Exclude<DetailChartPanelKey, "kline">;
  point: DetailChartPoint | null;
}) {
  const title = panel === "macd" ? "MACD(12,26,9)" : panel === "volume" ? "成交量" : "KDJ(9,3,3)";
  const metrics = point ? panelMetrics(panel, point) : [];
  return (
    <>
      <strong>{title}</strong>
      {metrics.map(({ display, label, value }) => (
        <span
          className={`metric ${directionClass(isFiniteChartNumber(value) && value >= 0 ? "UP" : "DOWN")}`}
          key={label}
        >
          {label}:{display ?? formatPanelMetric(value)}
        </span>
      ))}
      <button className="detail-chart-gear" title="指标设置" type="button">⚙</button>
    </>
  );
}

function panelMetrics(
  panel: Exclude<DetailChartPanelKey, "kline">,
  point: DetailChartPoint,
): Array<{ display?: string; label: string; value: number | null }> {
  if (panel === "macd") return [
    { label: "MACD", value: point.macd },
    { label: "DIF", value: point.dif },
    { label: "DEA", value: point.dea },
  ];
  if (panel === "volume") {
    return [
      { display: point.volumeDisplay ?? "--", label: "总量", value: point.volume },
      { label: "MA5", value: readStockFactor(point, "ma5") },
      { label: "MA10", value: readStockFactor(point, "ma10") },
    ];
  }
  return [
    { label: "K", value: point.k },
    { label: "D", value: point.d },
    { label: "J", value: point.j },
  ];
}

const STOCK_INDICATOR_PANELS = new Map<string, DetailChartIndicatorPanelKey>([
  ["VOL", "volume"],
  ["MACD", "macd"],
  ["KDJ", "kdj"],
]);

function StockIndicatorBar({
  indicatorControls,
  indicatorTabs,
  nineTurnControl,
  onOpenPriceTarget,
  onOverlayChange,
  overlay,
  supportsTrendChannel,
}: {
  indicatorControls: DetailChartIndicatorControls;
  indicatorTabs: StockIndicatorTab[];
  nineTurnControl: NineTurnDisplayControl;
  onOpenPriceTarget?: (trigger: HTMLButtonElement) => void;
  onOverlayChange: (overlay: StockMainOverlay | null) => void;
  overlay: StockMainOverlay | null;
  supportsTrendChannel: boolean;
}) {
  return (
    <div className="detail-chart-indicator-tabs">
      {indicatorTabs.map((tab) => {
        const panel = STOCK_INDICATOR_PANELS.get(tab.key);
        if (panel) {
          return (
            <Fragment key={tab.key}>
              <DetailChartIndicatorToggle panel={panel} indicatorControls={indicatorControls} />
              {panel === "kdj" && <NineTurnIndicatorToggle control={nineTurnControl} />}
            </Fragment>
          );
        }
        const tabOverlay = tab.overlay;
        if (!tabOverlay) return null;
        return (
          <button
            aria-pressed={tab.key === "MA" ? overlay === "MA" : undefined}
            className={buildIndicatorClass(tab, overlay)}
            key={tab.key}
            type="button"
            onClick={() => onOverlayChange(tabOverlay === "MA" && overlay === "MA" ? null : tabOverlay)}
          >
            {tab.label}
          </button>
        );
      })}
      {supportsTrendChannel ? (
        <button
          className={`detail-chart-indicator-tab ${overlay === "TREND_CHANNEL" ? "active" : ""}`}
          type="button"
          onClick={() => onOverlayChange("TREND_CHANNEL")}
        >
          趋势通道
        </button>
      ) : null}
      {onOpenPriceTarget && <button type="button" className="detail-chart-indicator-tab" aria-haspopup="dialog"
        onClick={(event) => onOpenPriceTarget(event.currentTarget)}>单阳测顶</button>}
    </div>
  );
}

function StockKlineTooltip({ point, side, daily }: { point: DetailChartPoint; side: DetailChartTooltipSide; daily: boolean }) {
  const rows: Array<[string, string, string]> = [
    ["时间", point.fullDate.replaceAll("-", ""), "secondary"],
    ["开盘", formatTooltipNumber(point.open), directionClass(resolvePriceDirection(point.open, point.preClose))],
    ["收盘", formatTooltipNumber(point.close), directionClass(resolvePriceDirection(point.close, point.open, { equalAsDown: true }))],
    ["最高", formatTooltipNumber(point.high), directionClass(resolvePriceDirection(point.high, point.open, { equalAsDown: true }))],
    ["最低", formatTooltipNumber(point.low), directionClass(resolvePriceDirection(point.low, point.preClose, { equalAsDown: true }))],
    ["涨幅", `${formatTooltipNumber(point.changePct)}%`, directionClass(resolveValueDirection(point.changePct))],
    ["成交量", point.volumeDisplay ?? "--", "secondary"],
    ["成交额", formatTooltipAmount(point.amount), "secondary"],
  ];
  if (daily) {
    rows.splice(6, 0, ["振幅", `${formatTooltipNumber(point.amplitude)}%`, "secondary"]);
    rows.push(["换手率", `${formatTooltipNumber(point.turnoverRate)}%`, "secondary"]);
  }
  return (
    <div className={`detail-chart-tooltip ${side}`}>
      <div className="detail-chart-tooltip-grid">
        {rows.map(([label, value, tone]) => (
          <div className="detail-chart-tooltip-row" key={label}>
            <span>{label}</span>
            <b className={tone}>{value}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

function buildIndicatorClass(tab: StockIndicatorTab, overlay: StockMainOverlay | null): string {
  const isActive = tab.overlay ? tab.overlay === overlay : tab.active;
  return ["detail-chart-indicator-tab", isActive ? "active" : "", tab.supported ? "" : "unsupported"]
    .filter(Boolean)
    .join(" ");
}

type StockFactorKey =
  | "ma5"
  | "ma10"
  | "ma20"
  | "ma30"
  | "ma60"
  | "ma90"
  | "ma250"
  | "bollUpper"
  | "bollMiddle"
  | "bollLower";

function readStockFactor(point: DetailChartPoint, key: StockFactorKey): number | null {
  return point.overlays[key] ?? null;
}

function resolvePriceDirection(
  value: number | null,
  base: number | null,
  options: { equalAsDown?: boolean } = {},
): MarketDirection {
  if (!isFiniteChartNumber(value) || !isFiniteChartNumber(base)) return "UNKNOWN";
  if (value > base) return "UP";
  if (value < base) return "DOWN";
  return options.equalAsDown ? "DOWN" : "FLAT";
}

function resolveValueDirection(value: number | null): MarketDirection {
  if (!isFiniteChartNumber(value)) return "UNKNOWN";
  if (value > 0) return "UP";
  if (value < 0) return "DOWN";
  return "FLAT";
}

function formatMetric(value: number | null): string {
  return isFiniteChartNumber(value) ? value.toFixed(2) : "--";
}

function finiteTrendValue(value: number | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatPanelMetric(value: number | null): string {
  if (!isFiniteChartNumber(value)) return "--";
  return Math.abs(value) > 999 ? String(Math.round(value)) : value.toFixed(2);
}

function formatTooltipNumber(value: number | null): string {
  return isFiniteChartNumber(value) ? value.toFixed(2) : "--";
}

function formatTooltipAmount(value: number | null): string {
  if (!isFiniteChartNumber(value)) return "--";
  if (value >= 100_000) return `${(value / 100_000).toFixed(2)}亿`;
  if (value >= 10) return `${(value / 10).toFixed(2)}万`;
  return value.toFixed(2);
}
