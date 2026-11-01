import { useCallback, useEffect, useMemo, useState } from "react";
import { useDailyWaveReview } from "../daily-wave/useDailyWaveReview";
import { useDailyWaveCompanionLayers } from "../daily-wave/useDailyWaveCompanionLayers";
import { DailyWavePrimitive } from "../daily-wave/DailyWavePrimitive";
import { DailyWaveLayerUi, DailyWaveLegend, DailyWaveResearchDetails } from "../daily-wave/DailyWaveLayerUi";
import { buildDailyWavePresentation } from "../daily-wave/presentation";
import type { DailyWaveMarkerIssue } from "../daily-wave/markerGeometry";
import { toDetailChartPoint } from "../chart/indexChartPointAdapter";
import { buildNineTurnRenderMarkers } from "../../nine-turn/model/nineTurnChartAdapter";
import { TrendChannelPanePrimitive } from "../../../shared/charts/trend-channel/TrendChannelPanePrimitive";
import { buildTrendChannelLines } from "../../../shared/charts/trend-channel/trendChannelGeometry";
import { XxmDebugDetails } from "./XxmDebugDetails";
import { ForecastDebugDetails } from "./ForecastDebugDetails";
import type { IndexRecognitionDebugProps, IndexRecognitionDebugExtension, IndexRecognitionDebugModule } from "./types";
export { decodeXxmDebug } from "./xxmDebugContract";
export { decodeForecastDebug } from "./forecastDebugContract";
export const renderXxmDetails: IndexRecognitionDebugModule["renderXxmDetails"] = (layer, time) => <XxmDebugDetails layer={layer} time={time}/>;
export const renderForecastDetails: IndexRecognitionDebugModule["renderForecastDetails"] = (response) => <ForecastDebugDetails response={response}/>;
const PADDING = { top: 44, bottom: 44 };
export function IndexRecognitionDebug(props: IndexRecognitionDebugProps) {
    return props.activePeriod === "day" ? <DailyWaveController {...props}/> : null;
}
function DailyWaveController({ ownerKey, tsCode, activePeriod, ordinaryAsOfDate, supportsNineTurn, supportsTrend, onChange }: IndexRecognitionDebugProps) {
    const enabled = import.meta.env.DEV && tsCode === "000001.SH" && ordinaryAsOfDate !== null;
    const review = useDailyWaveReview({ tsCode, activePeriod, enabled, ownerKey });
    const response = review.response?.status === "ready" ? review.response : null;
    const ready = review.phase === "ready" && response !== null;
    const layers = useDailyWaveCompanionLayers({ active: ready, endDate: ready ? response.observationEnd : null, tsCode, supportsNineTurn, supportsTrend });
    const points = useMemo(() => review.candles.map(toDetailChartPoint), [review.candles]);
    const dataKey = review.dataKey;
    const [layout, setLayout] = useState<{
        key: string | null;
        issues: readonly DailyWaveMarkerIssue[];
    }>({ key: null, issues: [] });
    const reportIssues = useCallback((issues: readonly DailyWaveMarkerIssue[]) => setLayout(previous => previous.key === dataKey && JSON.stringify(previous.issues) === JSON.stringify(issues) ? previous : { key: dataKey, issues }), [dataKey]);
    const presentation = useMemo(() => response ? buildDailyWavePresentation(response, ready && layout.key === dataKey ? layout.issues : []) : null, [response, ready, layout, dataKey]);
    const primitive = useMemo(() => new DailyWavePrimitive(), [dataKey]);
    const trendPrimitive = useMemo(() => new TrendChannelPanePrimitive([]), [dataKey]);
    const waveMainPrimitives = useMemo(() => [primitive], [primitive]);
    const trendMainPrimitives = useMemo(() => [trendPrimitive], [trendPrimitive]);
    const nineMarkers = useMemo(() => buildNineTurnRenderMarkers(layers.nineTurnLayer.markers, points, "daily").markers, [layers.nineTurnLayer.markers, points]);
    useEffect(() => { primitive.setData({ points, markers: ready ? presentation?.markers ?? [] : [], nineTurnMarkers: nineMarkers, onIssues: reportIssues }); }, [primitive, points, ready, presentation, nineMarkers, reportIssues]);
    useEffect(() => { trendPrimitive.setLines(ready && layers.trend ? buildTrendChannelLines(layers.trend.points, points.map(p => String(p.time))) : []); }, [trendPrimitive, ready, layers.trend, points]);
    useEffect(() => () => primitive.detached(), [primitive]);
    const renderWaveDetails = useCallback((point: Parameters<IndexRecognitionDebugExtension['renderWaveDetails']>[0]) => ready && response && presentation ? <DailyWaveResearchDetails response={response} facts={presentation.byDate.get(point.fullDate.slice(0, 10)) ?? []}/> : null, [ready, response, presentation]);
    const controls = useMemo(() => <DailyWaveLayerUi review={review} presentation={presentation}/>, [review.supported, review.enabled, review.phase, review.response, review.errorMessage, review.toggle, review.retry, review.close, presentation]);
    const extension = useMemo<IndexRecognitionDebugExtension>(() => ({ ownerKey, reviewPhase: review.phase, controls, legend: ready && response ? <DailyWaveLegend response={response}/> : null, renderWaveDetails,
        chartOverride: ready && dataKey ? { candles: review.candles, dataKey, nineTurnLayer: layers.nineTurnLayer, trend: layers.trend, trendPhase: layers.trendPhase, onNineTurnRetry: layers.retryNineTurn, onTrendRetry: layers.retryTrend, waveMainPrimitives, trendMainPrimitives, mainPriceScalePaddingPx: PADDING } : null }), [ownerKey, review.phase, controls, ready, response, renderWaveDetails, dataKey, review.candles, layers.nineTurnLayer, layers.trend, layers.trendPhase, layers.retryNineTurn, layers.retryTrend, waveMainPrimitives, trendMainPrimitives]);
    useEffect(() => { onChange(ownerKey, enabled ? extension : null); }, [onChange, ownerKey, enabled, extension]);
    useEffect(() => () => onChange(ownerKey, null), [ownerKey, onChange]);
    return null;
}
