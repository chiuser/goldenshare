import type { ReactNode } from "react";
import type { ISeriesPrimitive, Time } from "lightweight-charts";

export type DetailChartPanelKey = "kline" | "macd" | "volume" | "kdj";
export type DetailChartTooltipSide = "left" | "right";

export interface DetailChartPoint {
  time: string;
  fullDate: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  preClose: number | null;
  changePct: number | null;
  amplitude: number | null;
  volume: number | null;
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

export interface DetailChartWorkspaceProps {
  ariaLabel: string;
  bottomBar: ReactNode;
  bottomBarAriaLabel: string;
  isDailyPeriod: boolean;
  mainLines: DetailChartLineDefinition[];
  mainPrimitives?: ISeriesPrimitive<Time>[];
  panelAriaLabels: Record<DetailChartPanelKey, string>;
  points: DetailChartPoint[];
  renderMainHeader: (point: DetailChartPoint | null) => ReactNode;
  renderPanelHeader: (panel: Exclude<DetailChartPanelKey, "kline">, point: DetailChartPoint | null) => ReactNode;
  renderTooltip: (point: DetailChartPoint, side: DetailChartTooltipSide) => ReactNode;
  timeAxisAriaLabel: string;
  visibleBars?: number;
}

export interface DetailChartTimeAxisMarker {
  key: string;
  label: string;
  left: number;
  tone: "year" | "month";
}
