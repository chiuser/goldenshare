import type { MarketDirection } from "../../../shared/model/market";
import type {
  IndexDetailDataStatusDto,
  IndexDetailMinuteFrequency,
  IndexDetailPageInitResponseDto,
  IndexMinuteDataStatusDto,
} from "../api/indexDetailApiTypes";

export type IndexInfoTab = "basic" | "weights" | "technical";
export type IndexMainOverlay = "MA" | "BOLL" | "TREND_CHANNEL";
export type IndexPeriodKey = "timeShare" | "day" | "week" | "month" | "m120" | "m90" | "m60" | "m30" | "m15" | "m5" | "m1";
export type IndexPagePhase = "loading" | "ready" | "delayed" | "partial" | "empty" | "notFound" | "forbidden" | "error";
export type IndexDataPagePhase = "ready" | "delayed" | "partial";
export type IndexModulePhase = "idle" | "loading" | "ready" | "delayed" | "partial" | "empty" | "error";

export interface IndexPeriodOption {
  key: IndexPeriodKey;
  label: string;
  supported: boolean;
}

export interface IndexIndicatorTab {
  key: "VOL" | "amount" | "MA" | "MACD" | "KDJ" | "BOLL";
  label: string;
  overlay?: Exclude<IndexMainOverlay, "TREND_CHANNEL">;
  supported: boolean;
}

export interface IndexCandlePoint {
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
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma30: number | null;
  ma60: number | null;
  ma90: number | null;
  ma250: number | null;
  bollUpper: number | null;
  bollMiddle: number | null;
  bollLower: number | null;
  macd: number | null;
  dif: number | null;
  dea: number | null;
  k: number | null;
  d: number | null;
  j: number | null;
}

export interface IndexMinuteCandlePoint extends Omit<IndexCandlePoint, "time"> {
  time: number;
}

export interface IndexMinuteChartViewModel {
  tsCode: string;
  freq: IndexDetailMinuteFrequency;
  points: IndexMinuteCandlePoint[];
  dataStatus: IndexMinuteDataStatusDto;
  indicatorSource: "gold" | "unavailable";
  paramsKey: string | null;
  indicatorVersion: number | null;
}

export interface IndexMinuteSeriesState {
  data: IndexMinuteChartViewModel | null;
  errorMessage: string;
  phase: "idle" | "loading" | "ready" | "delayed" | "partial" | "empty" | "error";
}

export interface IndexBasicMetric {
  key: string;
  label: string;
  value: string;
  tone: "up" | "down" | "flat" | "secondary";
}

export interface IndexDetailViewModel {
  pageContext: IndexDetailPageInitResponseDto["pageContext"];
  asOfTradeDate: string | null;
  identity: IndexDetailPageInitResponseDto["index"];
  quote: IndexQuoteDisplay;
  basicMetrics: IndexBasicMetric[];
  periods: IndexPeriodOption[];
  indicatorTabs: IndexIndicatorTab[];
  chart: { candles: IndexCandlePoint[] };
  capabilities: IndexDetailPageInitResponseDto["capabilities"];
  dataStatus: IndexDetailDataStatusDto;
}

export interface TrendChannelPoint {
  time: string;
  close: number;
  shortUpper: number;
  shortLower: number;
  longUpper: number;
  longLower: number;
}

export interface TrendChannelViewModel {
  points: TrendChannelPoint[];
  droppedCount: number;
  status: "READY" | "EMPTY" | "PARTIAL";
}

export interface IndexQuoteDisplay {
  point: number | null;
  change: number | null;
  changePct: number | null;
  direction: MarketDirection;
}
