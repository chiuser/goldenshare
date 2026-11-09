import { useIndexXxmLayer } from "../xxm/useIndexXxmLayer";
import type { XxmLayerProps } from "../xxm/IndexXxmLayer";
import { useXxmValuesAt } from "../xxm/XxmLayerUi";
import { eventLabel } from "../xxm/adapter";
import { XxmDebugDetails } from "./XxmDebugDetails";
import { fetchDebugXxm } from "./apiClient";
import { buildDebugXxmViewModel } from "./xxmAdapter";

export function IndexDebugXxmLayer({ children, ...input }: XxmLayerProps) {
  const layer = useIndexXxmLayer(input, fetchDebugXxm, buildDebugXxmViewModel);
  const valuesAt = useXxmValuesAt(layer.data);
  return children({
    ...layer, valuesAt, renderDetails: time => {
      const detail = layer.data?.byTime.get(time);
      if (!detail) return null;
      const point = detail.point;
      const state = point.ordinaryState === "NONE" ? "无钝化或结构"
        : `${point.ordinaryDirection === "TOP" ? "顶" : "底"}${point.ordinaryState === "DULL" ? "钝化" : "结构"}`;
      return <>
        <div className="xxm-tooltip" aria-label="顶底识别详情">
          <div className="xxm-tooltip-title">顶底识别 · r4.1</div>
          <div className="xxm-tooltip-row"><span>当前状态</span><b>{state}</b></div>
          <div className="xxm-tooltip-row"><span>当根事件</span><b>{detail.displayEvents.map(eventLabel).join(" / ") || "无新事件"}</b></div>
          <div className="xxm-tooltip-row"><span>发生时间</span><b>{point.time}</b></div>
        </div>
        <XxmDebugDetails layer={layer} time={time} />
      </>;
    },
  });
}
