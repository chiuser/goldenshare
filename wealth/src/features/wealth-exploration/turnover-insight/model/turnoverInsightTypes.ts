import type { DataStatus } from "../../../../shared/model/market";
import type { TurnoverInsightDirection } from "../api/turnoverInsightApi";

export interface TurnoverInsightAmountViewModel {
  amountYi: number | null;
  displayText: string;
  direction: TurnoverInsightDirection;
}

export interface TurnoverInsightAverageViewModel extends TurnoverInsightAmountViewModel {
  referenceLabel: string;
}

export interface TurnoverInsightAxisViewModel {
  minYi: number;
  maxYi: number;
  zeroYi: number | null;
  ticks: readonly { valueYi: number; displayText: string }[];
}

export interface TurnoverInsightChartPoint {
  time: string;
  showAxisLabel: boolean;
  currentAmountYi: number | null;
  currentDisplayText: string;
  previousAmountYi: number | null;
  previousDisplayText: string;
  deltaAmountYi: number | null;
  deltaDisplayText: string;
  deltaDirection: "up" | "down" | "flat";
}

export interface TurnoverInsightViewModel {
  status: DataStatus;
  tradingDay: {
    expectedTradeDate: string;
    observedTradeDate: string | null;
    previousObservedTradeDate: string | null;
  };
  asOf: string | null;
  summary: {
    current: TurnoverInsightAmountViewModel;
    previous: TurnoverInsightAmountViewModel;
    delta: TurnoverInsightAmountViewModel;
    avg5d: TurnoverInsightAverageViewModel;
    avg20d: TurnoverInsightAverageViewModel;
  };
  upperAxis: TurnoverInsightAxisViewModel | null;
  deltaAxis: TurnoverInsightAxisViewModel | null;
  points: readonly TurnoverInsightChartPoint[];
  message: string | null;
  exceptionCode: string | null;
}

export type TurnoverInsightViewState = "loading" | "ready" | "delayed" | "partial" | "empty" | "error";
