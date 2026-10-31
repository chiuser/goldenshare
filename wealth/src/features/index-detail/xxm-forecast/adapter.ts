import { XXM_SPEC_HASH } from "../xxm/types";
import { assert, keys, timeKey } from "../xxm/adapter";
import { XXM_FORECAST_VERSION, XXM_FORECAST_SPEC_HASH } from "./types";
import type { ForecastPeriod, ForecastResponse, ForecastDebugResponse } from "./types";
import type { DecodeForecastDebug } from "../debug/types";
const root = "tsCode period forecastVersion forecastSpecHash detectorSpecHash computedThrough requestedAsOf mode dataStatus ordinaryState direction targetEndpoint barsAhead status reasonCode forecastId display applicabilityText invalidationText refreshAfterMs";
export function adaptForecast(raw: unknown, options: {
    period: ForecastPeriod;
    asOf?: string;
    debug: 0 | 1;
    decodeDebug?: DecodeForecastDebug;
    check: () => void;
}): ForecastResponse | ForecastDebugResponse {
    const { period, check } = options;
    check();
    keys(raw, root + (options.debug ? " debug" : ""));
    assert(raw.tsCode === "000001.SH" && raw.period === period && raw.forecastVersion === XXM_FORECAST_VERSION && raw.forecastSpecHash === XXM_FORECAST_SPEC_HASH && raw.detectorSpecHash === XXM_SPEC_HASH);
    assert(raw.mode === (options.asOf ? "REPLAY" : "LATEST") && raw.requestedAsOf === (options.asOf ?? null));
    for (const stamp of [raw.computedThrough, raw.requestedAsOf, raw.targetEndpoint])
        if (stamp !== null)
            timeKey(stamp, period);
    assert(["READY", "DELAYED", "EMPTY"].includes(String(raw.dataStatus)) && ["READY", "NO_CANDIDATE", "PRECISION_PENDING", "DELAYED", "EMPTY"].includes(String(raw.status)));
    assert([null, "NONE", "DULL", "STRUCTURE"].includes(raw.ordinaryState as null) && [null, "TOP", "BOTTOM"].includes(raw.direction as null));
    assert((raw.targetEndpoint === null && raw.barsAhead === null) || (typeof raw.targetEndpoint === "string" && raw.barsAhead === 1 && typeof raw.computedThrough === "string" && raw.targetEndpoint > raw.computedThrough));
    if (raw.requestedAsOf !== null && raw.computedThrough !== null)
        assert(String(raw.computedThrough) <= String(raw.requestedAsOf));
    const reasons: Record<string, unknown[]> = { EMPTY: ["SOURCE_EMPTY"], DELAYED: ["SOURCE_DELAYED"], NO_CANDIDATE: ["ZERO_WAVE", "NO_REFERENCE", "NO_ENTRY_RANGE"], PRECISION_PENDING: ["CALIBRATION_FAILED", "ROUNDING_BOUNDARY"], READY: [null, "ROUNDING_BOUNDARY"] };
    assert(reasons[String(raw.status)]!.includes(raw.reasonCode));
    if (raw.dataStatus !== "READY")
        assert(raw.status === raw.dataStatus && raw.targetEndpoint === null);
    else
        assert(!["EMPTY", "DELAYED"].includes(String(raw.status)));
    if (raw.dataStatus === "EMPTY")
        assert(raw.computedThrough === null && raw.ordinaryState === null && raw.direction === null);
    else
        assert(raw.computedThrough !== null && raw.ordinaryState !== null);
    if (["DULL", "STRUCTURE"].includes(String(raw.ordinaryState)))
        assert(raw.direction !== null);
    if (raw.status === "READY")
        assert(raw.targetEndpoint !== null);
    if (raw.reasonCode === "CALIBRATION_FAILED")
        assert(raw.targetEndpoint === null);
    assert(typeof raw.forecastId === "string" && !!raw.forecastId && raw.refreshAfterMs === 60000);
    keys(raw.display, "statusLabel targetText conditionsText asOfText");
    assert(Object.values(raw.display).every(v => typeof v === "string" && v.length > 0) && typeof raw.applicabilityText === "string" && !!raw.applicabilityText && typeof raw.invalidationText === "string" && !!raw.invalidationText);
    const response = Object.fromEntries(root.split(" ").map(k => [k, raw[k]])) as unknown as ForecastResponse;
    if (options.debug) {
        assert(options.decodeDebug);
        const debug = options.decodeDebug(raw.debug, { response, period, asOf: options.asOf, check });
        check();
        return { ...response, debug };
    }
    check();
    return response;
}
