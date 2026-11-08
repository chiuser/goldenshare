import type { DetailChartIndicatorControls, DetailChartIndicatorPanelKey } from "./detailChartTypes";

const INDICATOR_LABELS = { volume: "VOL", macd: "MACD", kdj: "KDJ" } as const;

interface DetailChartIndicatorToggleProps {
  panel: DetailChartIndicatorPanelKey;
  indicatorControls: DetailChartIndicatorControls;
}

export function DetailChartIndicatorToggle({ panel, indicatorControls }: DetailChartIndicatorToggleProps) {
  const visible = !indicatorControls.hiddenIndicatorPanels.has(panel);
  return (
    <button
      aria-pressed={visible}
      className={`detail-chart-indicator-tab${visible ? " active" : ""}`}
      onClick={() => indicatorControls.onToggleIndicatorPanel(panel)}
      type="button"
    >
      {INDICATOR_LABELS[panel]}
    </button>
  );
}

export function DetailChartIndicatorToggles({ indicatorControls }: { indicatorControls: DetailChartIndicatorControls }) {
  return (
    <>
      <DetailChartIndicatorToggle panel="volume" indicatorControls={indicatorControls} />
      <DetailChartIndicatorToggle panel="macd" indicatorControls={indicatorControls} />
      <DetailChartIndicatorToggle panel="kdj" indicatorControls={indicatorControls} />
    </>
  );
}
