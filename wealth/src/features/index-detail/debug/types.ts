import type { XxmDebugData, XxmPeriod, XxmResponse } from "../xxm/types";
import type { ForecastDebugData, ForecastPeriod, ForecastResponse } from "../xxm-forecast/types";
export type DecodeXxmDebug = (raw: unknown, context: {
    response: XxmResponse;
    tsCode: string;
    period: XxmPeriod;
    check: () => void;
}) => XxmDebugData;
export type DecodeForecastDebug = (raw: unknown, context: {
    response: ForecastResponse;
    period: ForecastPeriod;
    asOf?: string;
    check: () => void;
}) => ForecastDebugData;
