import { useMemo, useState } from "react";

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
import type {
  StockCandlePoint,
  StockIndicatorTab,
  StockMainOverlay,
} from "../model/stockDetailTypes";

interface StockChartWorkspaceProps {
  candles: StockCandlePoint[];
  indicatorTabs: StockIndicatorTab[];
  nineTurnLayer: NineTurnLayerViewModel;
  onNineTurnRetry: () => void;
  onAction: (message: string) => void;
  tsCode: string;
}

export function StockChartWorkspace({
  candles,
  indicatorTabs,
  nineTurnLayer,
  onNineTurnRetry,
  onAction,
  tsCode,
}: StockChartWorkspaceProps) {
  const [overlay, setOverlay] = useState<StockMainOverlay>("MA");
  const points = useMemo(() => candles.map(toDetailChartPoint), [candles]);
  const mainLines = useMemo<DetailChartLineDefinition[]>(
    () => overlay === "MA" ? buildMaLines() : buildBollLines(),
    [overlay],
  );
  const dataKey = `stock:${tsCode}:day`;
  const nineTurnChartLayer = useNineTurnChartLayer({
    dataKey,
    layer: nineTurnLayer,
    points,
    timeMode: "daily",
  });

  return (
    <DetailChartWorkspace
      ariaLabel="左侧图表区"
      bottomBar={(
        <StockIndicatorBar
          indicatorTabs={indicatorTabs}
          onAction={onAction}
          onOverlayChange={setOverlay}
          overlay={overlay}
        />
      )}
      bottomBarAriaLabel="底部指标栏"
      dataKey={dataKey}
      mainLayerAccessory={(
        <NineTurnLayerStatus
          droppedMarkerCount={nineTurnChartLayer.droppedMarkerCount}
          layer={nineTurnLayer}
          onRetry={onNineTurnRetry}
        />
      )}
      mainLines={mainLines}
      mainPrimitives={nineTurnChartLayer.mainPrimitives}
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
          onOverlayChange={setOverlay}
          overlay={overlay}
          point={point}
        />
      )}
      renderPanelHeader={(panel, point) => <StockIndicatorPanelHeader panel={panel} point={point} />}
      renderTooltip={(point, side) => <StockKlineTooltip point={point} side={side} />}
      timeAxisAriaLabel="日线底部时间轴"
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
  onOverlayChange,
  overlay,
  point,
}: {
  onAction: (message: string) => void;
  onOverlayChange: (overlay: StockMainOverlay) => void;
  overlay: StockMainOverlay;
  point: DetailChartPoint | null;
}) {
  return (
    <>
      <select
        aria-label="主图指标切换"
        className="detail-chart-overlay-select"
        value={overlay}
        onChange={(event) => {
          onOverlayChange(event.target.value as StockMainOverlay);
          event.currentTarget.blur();
        }}
      >
        <option value="MA">MA 均线</option>
        <option value="BOLL">BOLL 布林线</option>
      </select>
      {point ? <StockKlineMetrics point={point} overlay={overlay} /> : null}
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

function StockKlineMetrics({ point, overlay }: { point: DetailChartPoint; overlay: StockMainOverlay }) {
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

function StockIndicatorBar({
  indicatorTabs,
  onAction,
  onOverlayChange,
  overlay,
}: {
  indicatorTabs: StockIndicatorTab[];
  onAction: (message: string) => void;
  onOverlayChange: (overlay: StockMainOverlay) => void;
  overlay: StockMainOverlay;
}) {
  return (
    <div className="detail-chart-indicator-tabs">
      {indicatorTabs.map((tab) => (
        <button
          className={buildIndicatorClass(tab, overlay)}
          key={tab.key}
          type="button"
          onClick={() => {
            if (tab.overlay) {
              onOverlayChange(tab.overlay);
              return;
            }
            onAction(`${tab.label} 指标暂未支持`);
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function StockKlineTooltip({ point, side }: { point: DetailChartPoint; side: DetailChartTooltipSide }) {
  const rows: Array<[string, string, string]> = [
    ["时间", point.fullDate.replaceAll("-", ""), "secondary"],
    ["开盘", formatTooltipNumber(point.open), directionClass(resolvePriceDirection(point.open, point.preClose))],
    ["收盘", formatTooltipNumber(point.close), directionClass(resolvePriceDirection(point.close, point.open, { equalAsDown: true }))],
    ["最高", formatTooltipNumber(point.high), directionClass(resolvePriceDirection(point.high, point.open, { equalAsDown: true }))],
    ["最低", formatTooltipNumber(point.low), directionClass(resolvePriceDirection(point.low, point.preClose, { equalAsDown: true }))],
    ["涨幅", `${formatTooltipNumber(point.changePct)}%`, directionClass(resolveValueDirection(point.changePct))],
    ["振幅", `${formatTooltipNumber(point.amplitude)}%`, "secondary"],
    ["成交量", point.volumeDisplay ?? "--", "secondary"],
    ["成交额", formatTooltipAmount(point.amount), "secondary"],
    ["换手率", `${formatTooltipNumber(point.turnoverRate)}%`, "secondary"],
  ];
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

function buildIndicatorClass(tab: StockIndicatorTab, overlay: StockMainOverlay): string {
  const isOverlayActive = tab.overlay && tab.overlay === overlay;
  const isActive = tab.active || isOverlayActive;
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
