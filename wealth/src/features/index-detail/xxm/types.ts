import type { Time } from "lightweight-charts";

export type XxmPeriod = "day" | "m60" | "m90" | "m120";
export type XxmDirection = "TOP" | "BOTTOM";
export interface XxmReference { startTime: string; endTime: string; price: number; dif: number }
export interface XxmPoint {
  time: string; close: number; dif: number; dea: number; hist: number;
  ordinaryState: "NONE" | "DULL" | "STRUCTURE";
  ordinaryDirection: XxmDirection | null;
  activeReference: XxmReference | null;
  pendingTopHistoryId: string | null;
  pendingBottomHistoryId: string | null;
  pendingRearmId: string | null;
}
export interface XxmEvent {
  id: string; time: string; direction: XxmDirection;
  type: "DULL" | "STRUCTURE" | "CANCEL" | "STRUCTURE_DISAPPEARED" | "RESEARCH_HISTORICAL_WITHDRAWAL";
  route: "activation" | "reactivation" | "dif_turn" | "dif_return" | "color_flip" | "dif_break" | "dif_break_on_flip" | "historical_price_break";
  fromState: XxmPoint["ordinaryState"];
  eventReference: XxmReference | null;
  relatedTopHistoryId: string | null;
  relatedBottomHistoryId: string | null;
  relatedRearmId: string | null;
}
export interface XxmHistory {
  id: string; confirmedAt: string; confirmationRoute: "dif_turn" | "color_flip";
  pricePeak: number; pricePeakAt: string; originalReference: XxmReference;
  status: "PENDING" | "ENDED"; endedAt: string | null;
  endReason: "original_reference_break" | "new_top_DULL" | "new_top_STRUCTURE" | "historical_price_break" | null;
  observedThrough: string; ageBars: number;
}
export interface XxmBottomHistory {
  id: string; structureEventId: string; confirmedAt: string; confirmationRoute: "dif_turn" | "color_flip";
  originSegmentStart: string; leftOriginAt: string | null; priceLow: number; priceLowAt: string;
  originalReference: XxmReference; status: "PENDING" | "ENDED"; endedAt: string | null;
  endReason: "original_reference_break" | "new_bottom_DULL" | "new_bottom_STRUCTURE" | "structure_disappeared" | "historical_price_break" | null;
  observedThrough: string; ageBars: number;
}
export interface XxmRearmRecord {
  id: string; direction: "BOTTOM"; bottomHistoryId: string; structureEventId: string;
  structureConfirmedAt: string; structureRoute: "dif_turn"; segmentStart: string;
  nearestPriceGate: number; reference: XxmReference; disappearedAt: string; observedThrough: string;
  status: "WAITING" | "REACTIVATED" | "INVALIDATED" | "SEGMENT_ENDED";
  endedAt: string | null; endReason: "price_requalified" | "reference_dif_break" | "color_flip" | "zero" | null;
}
export interface XxmResponse {
  tsCode: "000001.SH"; period: XxmPeriod; algorithmVersion: string; specHash: string;
  source: { kind: "daily_factor" | "minute_gold"; inputId: string; startTime: string | null;
    computedThrough: string | null; initialHistoryIncomplete: boolean; indicatorVersion: number | null };
  points: XxmPoint[]; events: XxmEvent[]; topHistories: XxmHistory[]; bottomHistories: XxmBottomHistory[]; rearmRecords: XxmRearmRecord[];
  meta: { count: number; responseStart: string | null; responseEnd: string | null };
  dataStatus: { status: "READY" | "DELAYED" | "EMPTY"; message: string | null; asOf: string | null };
}
export interface XxmMarker { time: Time; dif: number; event: XxmEvent }
export interface XxmDetail { point: XxmPoint; events: XxmEvent[]; histories: XxmHistory[]; bottomHistories: XxmBottomHistory[]; rearmRecords: XxmRearmRecord[] }
export interface XxmViewModel { response: XxmResponse; markers: XxmMarker[]; byTime: Map<string, XxmDetail> }
export interface XxmLayerState {
  requestKey: string; phase: "unsupported" | "loading" | "ready" | "empty" | "delayed" | "error";
  data: XxmViewModel | null; errorMessage: string;
}
