import type { WatchlistDirection } from "../api/watchlistApiTypes";

export interface WatchlistRowViewModel {
  id: number;
  tsCode: string;
  name: string;
  industry: string;
  price: string;
  changePct: string;
  vol: string;
  peTtm: string;
  pb: string;
  volumeRatio: string;
  turnoverRate: string;
  netAmount: string;
  priceDirection: WatchlistDirection;
  moneyFlowDirection: WatchlistDirection;
  missingFields: string[];
}
