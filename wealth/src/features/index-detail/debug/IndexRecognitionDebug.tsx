import { useCallback, useEffect, useMemo, useState } from "react";
import type { IndexChartAddonProps } from "../chart/IndexChartWorkspace";
import { useDailyWaveReview } from "../daily-wave/useDailyWaveReview";
import { DailyWavePrimitive } from "../daily-wave/DailyWavePrimitive";
import { DailyWaveLayerUi, DailyWaveLegend, DailyWaveResearchDetails } from "../daily-wave/DailyWaveLayerUi";
import { buildDailyWavePresentation } from "../daily-wave/presentation";
import type { DailyWaveMarkerIssue } from "../daily-wave/markerGeometry";

const PADDING = { top: 44, bottom: 44 };

export function IndexRecognitionDebug(props: IndexChartAddonProps) {
  return props.tsCode === "000001.SH" && props.asOfTradeDate !== null
    ? <DailyWaveController {...props} /> : props.children({});
}

function DailyWaveController({ ownerKey, tsCode, points, nineTurnMarkers, children }: IndexChartAddonProps) {
  const review = useDailyWaveReview({ tsCode, activePeriod: "day", enabled: true, ownerKey });
  const response = review.response?.status === "ready" ? review.response : null;
  const [layout, setLayout] = useState<{ id: string; issues: readonly DailyWaveMarkerIssue[] } | null>(null);
  const reportIssues = useCallback((issues: readonly DailyWaveMarkerIssue[]) => {
    if (!response) return;
    setLayout(previous => previous?.id === response.calculationId && JSON.stringify(previous.issues) === JSON.stringify(issues)
      ? previous : { id: response.calculationId, issues });
  }, [response]);
  const presentation = useMemo(() => response
    ? buildDailyWavePresentation(response, layout?.id === response.calculationId ? layout.issues : [])
    : null, [response, layout]);
  const primitive = useMemo(() => new DailyWavePrimitive(), [ownerKey]);
  const primitives = useMemo(() => [primitive], [primitive]);
  useEffect(() => {
    const dates = new Set(points.map(point => point.fullDate.slice(0, 10)));
    const markers = presentation?.markers.filter(marker => dates.has(marker.date)) ?? [];
    primitive.setData({ points, markers, nineTurnMarkers, onIssues: reportIssues });
  }, [primitive, points, presentation, nineTurnMarkers, reportIssues]);
  useEffect(() => () => primitive.detached(), [primitive]);
  return children({
    controls: <DailyWaveLayerUi review={review} presentation={presentation} />,
    legend: response ? <DailyWaveLegend response={response} /> : null,
    primitives: response ? primitives : undefined,
    padding: response ? PADDING : undefined,
    renderDetails: point => response && presentation
      ? <DailyWaveResearchDetails response={response} facts={presentation.byDate.get(point.fullDate.slice(0, 10)) ?? []} />
      : null,
  });
}
