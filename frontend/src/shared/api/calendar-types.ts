export interface MarketTradeCalendarItem {
  trade_date: string;
  is_open: boolean;
  pretrade_date: string | null;
}

export interface MarketTradeCalendarResponse {
  exchange: string;
  items: MarketTradeCalendarItem[];
}
