import { useEffect, useMemo, useRef } from "react";

import { NineTurnMarkerPrimitive } from "../../../shared/charts/detail-workspace/NineTurnMarkerPrimitive";
import type { DetailChartPoint, DetailChartTimeMode } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { buildNineTurnRenderMarkers } from "../model/nineTurnChartAdapter";
import type { NineTurnLayerViewModel } from "../model/nineTurnTypes";

export function useNineTurnChartLayer({
  dataKey,
  layer,
  points,
  timeMode,
}: {
  dataKey: string;
  layer: NineTurnLayerViewModel;
  points: readonly DetailChartPoint[];
  timeMode: DetailChartTimeMode;
}) {
  const adaptation = useMemo(
    () => buildNineTurnRenderMarkers(layer.markers, points, timeMode),
    [layer.markers, points, timeMode],
  );
  const primitiveState = useRef<{ dataKey: string; primitive: NineTurnMarkerPrimitive } | null>(null);
  if (primitiveState.current === null || primitiveState.current.dataKey !== dataKey) {
    primitiveState.current = {
      dataKey,
      primitive: new NineTurnMarkerPrimitive(adaptation.markers),
    };
  }
  const primitive = primitiveState.current.primitive;
  useEffect(() => {
    primitive.setMarkers(adaptation.markers);
  }, [adaptation.markers, primitive]);
  const mainPrimitives = useMemo(() => [primitive], [primitive]);
  return {
    droppedMarkerCount: adaptation.droppedMarkerCount,
    mainPrimitives,
  };
}
