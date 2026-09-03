import type { PageSessionStatus } from "../../../shared/ui/page-breadcrumb/PageBreadcrumb";

export type WatchlistDirection = "UP" | "DOWN" | "FLAT" | "UNKNOWN";
export type WatchlistDataStatus =
  "READY" | "DELAYED" | "PARTIAL" | "EMPTY" | "ERROR";
export interface WatchlistItemDto {
  id: number;
  addedAt: string;
  stock: {
    tsCode: string;
    name: string;
    industry: string | null;
    listStatus: string | null;
  };
  quote: {
    price: number | null;
    changePct: number | null;
    direction: WatchlistDirection;
    vol: number | null;
  };
  valuation: { peTtm: number | null; pb: number | null };
  activity: { volumeRatio: number | null; turnoverRate: number | null };
  moneyFlow: { netAmount: number | null; direction: WatchlistDirection };
  missingFields: string[];
}
export interface WatchlistPageResponseDto {
  pageContext: {
    market: "CN_A";
    tradeDate: string;
    prevTradeDate: string | null;
    isTradingDay: boolean;
    sessionStatus: PageSessionStatus;
    timezone: "Asia/Shanghai";
    generatedAt: string;
    source: "explicit" | "default";
  };
  dataStatus: {
    status: WatchlistDataStatus;
    expectedTradeDate: string;
    observedTradeDate: string | null;
  };
  items: WatchlistItemDto[];
  totalCount: number;
  nextCursor: number | null;
}
export interface WatchlistSummaryResponseDto {
  totalCount: number;
}
export interface WatchlistCandidateDto {
  tsCode: string;
  name: string;
  status: "AVAILABLE" | "ADDED";
}
export interface WatchlistSearchResponseDto {
  keyword: string;
  items: WatchlistCandidateDto[];
}
export interface WatchlistMembershipResponseDto {
  tsCode: string;
  isAdded: boolean;
}
export interface WatchlistAddResponseDto extends WatchlistMembershipResponseDto {
  created: boolean;
  totalCount: number;
}
export interface WatchlistRemoveResponseDto extends WatchlistMembershipResponseDto {
  removed: boolean;
  totalCount: number;
}
