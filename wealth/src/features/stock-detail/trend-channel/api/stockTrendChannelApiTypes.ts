export type StockTrendChannelPosition = "ABOVE" | "INSIDE" | "BELOW";
export type StockTrendChannelState = "UNKNOWN" | "UP" | "DOWN";
export type StockCombinedTrendChannelState = "UNKNOWN" | "UP_UP" | "UP_DOWN" | "DOWN_UP" | "DOWN_DOWN";

export interface StockTrendChannelBandDto {
  upper: number;
  lower: number;
  position: StockTrendChannelPosition;
  state: StockTrendChannelState;
}

export interface StockTrendChannelBarDto {
  tradeDate: string;
  open: number;
  high: number;
  low: number;
  close: number;
  shortChannel: StockTrendChannelBandDto;
  longChannel: StockTrendChannelBandDto;
  combinedState: StockCombinedTrendChannelState;
}

export interface StockTrendChannelResponseDto {
  stockRef: { tsCode: string; name?: string | null };
  period: "day";
  adjustment: "forward";
  sourceAdjustment: "qfq";
  formula: {
    key: "high-low-ema-hysteresis";
    version: "stock-daily-trend-channel-v1";
    shortPeriod: 25;
    longPeriod: 90;
    seed: "first_observation";
    stateRule: "strict_close_breakout_inside_retention";
  };
  bars: StockTrendChannelBarDto[];
  meta: { count: number; limit: number; endDate: string };
  dataStatus: {
    status: "READY" | "EMPTY";
    observedTradeDate?: string | null;
    note?: string | null;
  };
}
