import type { ComponentType, ReactNode } from "react";
import type { XxmDebugData, XxmLayerState, XxmPeriod, XxmResponse } from "../xxm/types";
import type { ForecastDebugData, ForecastDebugResponse, ForecastPeriod, ForecastResponse } from "../xxm-forecast/types";
import type { IndexCandlePoint, IndexPeriodKey, TrendChannelViewModel } from "../model/indexDetailTypes";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { ISeriesPrimitive, Time } from "lightweight-charts";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
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
export interface IndexRecognitionProps {
    recognitionEnabled: boolean;
    debug: 0 | 1;
    decodeXxmDebug?: DecodeXxmDebug;
    renderXxmDetails?: (layer: XxmLayerState, time: string) => ReactNode;
}
export interface IndexRecognitionDebugExtension {
    ownerKey: string;
    reviewPhase: string;
    chartOverride: {
        candles: IndexCandlePoint[];
        dataKey: string;
        nineTurnLayer: NineTurnLayerViewModel;
        trend: TrendChannelViewModel | null;
        trendPhase: "unavailable" | "loading" | "ready" | "error";
        onNineTurnRetry: () => void;
        onTrendRetry: () => void;
        waveMainPrimitives: ISeriesPrimitive<Time>[];
        trendMainPrimitives: ISeriesPrimitive<Time>[];
        mainPriceScalePaddingPx: {
            top: number;
            bottom: number;
        };
    } | null;
    controls: ReactNode;
    legend: ReactNode | null;
    renderWaveDetails: (point: DetailChartPoint) => ReactNode;
}
export interface IndexRecognitionDebugProps {
    ownerKey: string;
    tsCode: string;
    activePeriod: IndexPeriodKey;
    ordinaryAsOfDate: string | null;
    supportsNineTurn: boolean;
    supportsTrend: boolean;
    onChange: (ownerKey: string, extension: IndexRecognitionDebugExtension | null) => void;
}
export interface IndexRecognitionDebugModule {
    IndexRecognitionDebug: ComponentType<IndexRecognitionDebugProps>;
    decodeXxmDebug: DecodeXxmDebug;
    decodeForecastDebug: DecodeForecastDebug;
    renderXxmDetails: (layer: XxmLayerState, time: string) => ReactNode;
    renderForecastDetails: (response: ForecastDebugResponse) => ReactNode;
}
