import type { Time } from "lightweight-charts";
export const XXM_ALGORITHM_VERSION = "xxm-direction-v0.5-r4.1" as const;
export const XXM_SPEC_HASH = "a2554ffb510d36930ed22b03bf6b40d94b71e81636290ea666585e94fbf9e367";
const XXM_PERIODS = ["day", "m30", "m60", "m90", "m120"] as const;
export type XxmPeriod = typeof XXM_PERIODS[number];

export function isXxmPeriod(period: string): boolean {
    return XXM_PERIODS.some(supported => supported === period);
}
export type XxmDirection = "TOP" | "BOTTOM";
export interface XxmReference {
    startTime: string;
    endTime: string;
    price: number;
    dif: number;
    priceAt: string;
    difAt: string;
}
export interface XxmWave {
    sign: 1 | -1;
    start: string;
    end: string;
    count: number;
    price: number;
    dif: number;
    priceAt: string;
    difAt: string;
}
export interface XxmPoint {
    time: string;
    close: number;
    dif: number;
    dea: number;
    hist: number;
    ordinaryState: "NONE" | "DULL" | "STRUCTURE";
    ordinaryDirection: XxmDirection | null;
}
export interface XxmEvent {
    id: string;
    time: string;
    direction: XxmDirection;
    type: "DULL" | "STRUCTURE" | "CANCEL";
    displayOnChart: boolean;
}
export interface XxmDebugPoint {
    time: string;
    activeReference: XxmReference | null;
    activeStructureId: string | null;
}
export interface XxmDebugEvent {
    id: string;
    route: "activation" | "dif_turn" | "dif_return" | "color_flip" | "dif_break" | "dif_break_on_flip" | "structure_price_break";
    fromState: XxmPoint["ordinaryState"];
    eventReference: XxmReference;
    relatedStructureId: string | null;
}
export interface XxmStructure {
    id: string;
    direction: XxmDirection;
    structureEventId: string;
    formedAt: string;
    formationRoute: "dif_turn" | "color_flip";
    originSegmentStart: string;
    originalReference: XxmReference;
    priceExtreme: number;
    priceExtremeAt: string;
    status: "ASSESSING" | "FOLLOWING" | "FINISHED" | "DISAPPEARED";
    originWave: XxmWave | null;
    firstOppositeAt: string | null;
    nextSameColorStart: string | null;
    nextSameColorCount: number;
    trackingPriceExtreme: number | null;
    trackingPriceExtremeAt: string | null;
    trackingEndedAt: string | null;
    disappearedAt: string | null;
    disappearanceReason: "dif_return" | "reference_dif_break" | "structure_price_break" | null;
}
export interface XxmResponse {
    tsCode: string;
    period: XxmPeriod;
    algorithmVersion: string;
    specHash: string;
    source: {
        kind: "daily_factor" | "minute_gold";
        startTime: string | null;
        computedThrough: string | null;
        initialHistoryIncomplete: boolean;
        indicatorVersion: number | null;
    };
    points: XxmPoint[];
    events: XxmEvent[];
    meta: {
        count: number;
        responseStart: string | null;
        responseEnd: string | null;
    };
    dataStatus: {
        status: "READY" | "DELAYED" | "EMPTY";
        message: string | null;
        asOf: string | null;
    };
}
export interface GoldXxmPoint extends Omit<XxmPoint, "ordinaryState" | "ordinaryDirection"> {
    ordinaryState: null;
    ordinaryDirection: null;
}
export interface GoldXxmResponse extends Omit<XxmResponse, "source" | "points"> {
    points: GoldXxmPoint[];
}
export type XxmHistoryResponse = GoldXxmResponse | XxmResponse | XxmDebugResponse;

export interface XxmDebugData {
    sourceInputId: string;
    points: XxmDebugPoint[];
    events: XxmDebugEvent[];
    structures: XxmStructure[];
}
export interface XxmDebugResponse extends XxmResponse {
    debug: XxmDebugData;
}
export interface XxmMarker {
    time: Time;
    dif: number;
    event: XxmEvent;
}
export interface XxmDetail {
    point: XxmPoint | GoldXxmPoint;
    events: XxmEvent[];
    displayEvents: XxmEvent[];
    debugDetail: {
        point: XxmDebugPoint;
        events: XxmDebugEvent[];
        structures: XxmStructure[];
    } | null;
}
export interface XxmViewModel {
    response: XxmHistoryResponse;
    markers: XxmMarker[];
    byTime: Map<string, XxmDetail>;
}
export interface XxmLayerState {
    requestKey: string;
    phase: "unsupported" | "loading" | "ready" | "empty" | "delayed" | "error";
    data: XxmViewModel | null;
    errorMessage: string;
}
export interface XxmRequestResult {
    response: XxmHistoryResponse;
    deadline: number;
}
