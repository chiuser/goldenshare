import type { WatchlistDirection, WatchlistGroupMarkDto } from "../api/watchlistApiTypes";
export interface WatchlistRowViewModel {
  membershipId: number;
  isPinned: boolean;
  groupMarks: WatchlistGroupMarkDto[];
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
export type WatchlistMutation<A, R> = {
  kind: "idle";
} | {
  kind: "pending";
  action: A;
} | {
  kind: "succeeded";
  action: A;
  result: R;
} | {
  kind: "failed";
  action: A;
  error: Error;
} | {
  kind: "unknown";
  action: A;
};
export const mutationLocked = (mutation: {
  kind: string;
}) => mutation.kind === "pending" || mutation.kind === "unknown";
export const watchlistError = (error: unknown) => error instanceof Error ? error : new Error("自选操作失败，请重试");
