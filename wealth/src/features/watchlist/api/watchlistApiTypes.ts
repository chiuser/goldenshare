import type { PageSessionStatus } from "../../../shared/ui/page-breadcrumb/PageBreadcrumb";
export type WatchlistDirection = "UP" | "DOWN" | "FLAT" | "UNKNOWN";
export type WatchlistDataStatus = "READY" | "DELAYED" | "PARTIAL" | "EMPTY" | "ERROR";
export interface WatchlistItemDto {
  membershipId: number;
  addedAt: string;
  isPinned: boolean;
  groupMarks: WatchlistGroupMarkDto[];
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
  valuation: {
    peTtm: number | null;
    pb: number | null;
  };
  activity: {
    volumeRatio: number | null;
    turnoverRate: number | null;
  };
  moneyFlow: {
    netAmount: number | null;
    direction: WatchlistDirection;
  };
  missingFields: string[];
}
export interface WatchlistPageResponseDto {
  group: WatchlistGroupDto;
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
  nextCursor: string | null;
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
  groupId: number;
  keyword: string;
  items: WatchlistCandidateDto[];
}
export interface WatchlistAddResponseDto {
  groupId: number;
  tsCode: string;
  isAdded: true;
  created: boolean;
  memberCount: number;
}
export interface WatchlistGroupDto {
  id: number;
  name: string;
  isDefault: boolean;
  color: string | null;
  memberCount: number;
  createdAt: string;
}
export interface WatchlistGroupRulesDto {
  maxGroups: number;
  maxCustomGroups: number;
  nameMaxVisibleChars: number;
  nameMaxUtf8Bytes: number;
  maxBatchMemberships: number;
  palette: string[];
}
export interface WatchlistGroupsResponseDto {
  groups: WatchlistGroupDto[];
  rules: WatchlistGroupRulesDto;
}
export interface WatchlistGroupMutationResponseDto {
  group: WatchlistGroupDto;
}
export interface WatchlistGroupDeleteResponseDto {
  deletedGroupId: number;
  deletedMemberCount: number;
  nextGroupId: number;
}
export interface WatchlistGroupMarkDto {
  groupId: number;
  name: string;
  color: string;
}
export type WatchlistSortField = "price" | "changePct" | "vol" | "peTtm" | "pb" | "volumeRatio" | "turnoverRate" | "netAmount";
export interface WatchlistSort {
  sortBy: WatchlistSortField;
  direction: "desc" | "asc";
}
export type WatchlistBatchAction = "MOVE" | "ADD_TO_GROUPS" | "REMOVE" | "PIN" | "UNPIN";
export interface WatchlistBatchActionResponseDto {
  action: WatchlistBatchAction;
  requestedCount: number;
  createdCount: number;
  removedCount: number;
  updatedCount: number;
  groupCounts: {
    groupId: number;
    memberCount: number;
  }[];
}
export interface WatchlistStockGroupDto {
  groupId: number;
  name: string;
  isDefault: boolean;
  color: string | null;
  selected: boolean;
}
export interface WatchlistStockGroupsResponseDto {
  tsCode: string;
  isAdded: boolean;
  groups: WatchlistStockGroupDto[];
}
export interface WatchlistStockGroupsReplaceResponseDto {
  tsCode: string;
  isAdded: true;
  groupIds: number[];
  createdCount: number;
  removedCount: number;
}
