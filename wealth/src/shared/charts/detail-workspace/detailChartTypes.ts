import type { ReactNode } from "react";
import type { ISeriesPrimitive, Time, UTCTimestamp } from "lightweight-charts";

export type DetailChartPanelKey = "kline" | "macd" | "volume" | "kdj";
export type DetailChartTooltipSide = "left" | "right";
export type DetailChartTimeMode = "daily" | "minute";
export type DetailChartTimeAxisPlacement = "bottom-pane" | "each-pane";
export type DetailChartCrosshairPresentation = "synchronized-overlay" | "native-axis-labels";

export interface DetailChartPoint {
  time: string | UTCTimestamp;
  fullDate: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  preClose: number | null;
  changePct: number | null;
  amplitude: number | null;
  volume: number | null;
  volumeDisplay: string | null;
  amount: number | null;
  turnoverRate: number | null;
  macd: number | null;
  dif: number | null;
  dea: number | null;
  k: number | null;
  d: number | null;
  j: number | null;
  overlays: Readonly<Record<string, number | null>>;
}

export interface DetailChartLineDefinition {
  color: string;
  id: string;
  valueOf: (point: DetailChartPoint) => number | null;
}

export interface DetailChartAxisFloatLabelState {
  panel: DetailChartPanelKey;
  top: number;
  value: string;
}

interface DetailChartWorkspaceBaseProps {
  dataKey: string;
  ariaLabel: string;
  crosshairPresentation?: DetailChartCrosshairPresentation;
  mainLines: DetailChartLineDefinition[];
  mainLayerAccessory?: ReactNode;
  mainPrimitives?: ISeriesPrimitive<Time>[];
  panelAriaLabels: Record<DetailChartPanelKey, string>;
  points: DetailChartPoint[];
  renderMainHeader: (point: DetailChartPoint | null) => ReactNode;
  renderPanelHeader: (panel: Exclude<DetailChartPanelKey, "kline">, point: DetailChartPoint | null) => ReactNode;
  renderTooltip: (point: DetailChartPoint, side: DetailChartTooltipSide) => ReactNode;
  timeAxisAriaLabel: string;
  timeAxisPlacement?: DetailChartTimeAxisPlacement;
  timeMode: DetailChartTimeMode;
  topRightAccessory?: ReactNode;
}

type DetailChartBottomBarProps =
  | { bottomBar: ReactNode; bottomBarAriaLabel: string }
  | { bottomBar?: never; bottomBarAriaLabel?: never };

export type DetailChartWorkspaceProps = DetailChartWorkspaceBaseProps & DetailChartBottomBarProps;

export interface DetailChartTimeAxisMarker {
  key: string;
  label: string;
  left: number;
  tone: "year" | "month";
}
