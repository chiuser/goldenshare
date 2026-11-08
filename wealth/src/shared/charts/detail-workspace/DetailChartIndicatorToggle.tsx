import type { DetailChartIndicatorControls, DetailChartIndicatorPanelKey } from "./detailChartTypes";

const INDICATOR_LABELS = { volume: "VOL", macd: "MACD", kdj: "KDJ", quantitativeStructure: "量化结构" } as const;
type IndicatorToggleMode = "available" | "disabled" | "placeholder";

interface DetailChartIndicatorToggleProps {
  panel: DetailChartIndicatorPanelKey;
  indicatorControls: DetailChartIndicatorControls;
  mode?: IndicatorToggleMode;
}

export function DetailChartIndicatorToggle({ panel, indicatorControls, mode = "available" }: DetailChartIndicatorToggleProps) {
  const visible = mode === "available" && !indicatorControls.hiddenIndicatorPanels.has(panel);
  return (
    <button
      aria-pressed={visible}
      className={`detail-chart-indicator-tab${visible ? " active" : ""}${mode === "disabled" ? " unsupported" : ""}`}
      disabled={mode === "disabled"}
      onClick={mode === "available" ? () => indicatorControls.onToggleIndicatorPanel(panel) : undefined}
      type="button"
    >
      {INDICATOR_LABELS[panel]}
    </button>
  );
}

export function DetailChartIndicatorToggles({
  indicatorControls,
  quantitativeStructureMode = indicatorControls.quantitativeStructureAvailable ? "available" : "disabled",
}: {
  indicatorControls: DetailChartIndicatorControls;
  quantitativeStructureMode?: IndicatorToggleMode;
}) {
  return (
    <>
      <DetailChartIndicatorToggle panel="volume" indicatorControls={indicatorControls} />
      <DetailChartIndicatorToggle panel="macd" indicatorControls={indicatorControls} />
      <DetailChartIndicatorToggle panel="kdj" indicatorControls={indicatorControls} />
      <DetailChartIndicatorToggle panel="quantitativeStructure" indicatorControls={indicatorControls} mode={quantitativeStructureMode} />
    </>
  );
}
