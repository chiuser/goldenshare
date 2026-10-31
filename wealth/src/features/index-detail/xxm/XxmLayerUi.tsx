import { eventLabel } from "./adapter";
import type { XxmLayerState } from "./types";
import "./xxm-layer.css";
export function XxmLayerStatus({layer,onRetry}:{layer:XxmLayerState;onRetry:()=>void}){
  if(layer.phase==="unsupported")return null;
  const status=layer.phase==="loading"?"正在加载顶底识别":layer.phase==="empty"?"顶底识别暂无数据":layer.phase==="error"?"顶底识别加载失败":layer.phase==="delayed"?layer.data?.response.dataStatus.message:"";
  if(!status)return null;
  return <span className={`xxm-layer-status ${layer.phase}`} role="status" title={layer.errorMessage||status||undefined}><span className="xxm-status-message">{status}</span>{layer.phase==="error"?<button aria-label="重试顶底识别" onClick={onRetry} type="button">重试</button>:null}</span>;
}
export function XxmSignalDetails({layer,time}:{layer:XxmLayerState;time:string}){
  const detail=layer.data?.byTime.get(time);if(!detail)return null;
  const point=detail.point,state=point.ordinaryState==="NONE"?"无钝化或结构":`${point.ordinaryDirection==="TOP"?"顶":"底"}${point.ordinaryState==="DULL"?"钝化":"结构"}`;
  return <div className="xxm-tooltip" aria-label="顶底识别详情"><div className="xxm-tooltip-title">顶底识别 · r4</div><div className="xxm-tooltip-row"><span>当前状态</span><b>{state}</b></div><div className="xxm-tooltip-row"><span>当根事件</span><b>{detail.displayEvents.map(eventLabel).join(" / ")||"无新事件"}</b></div><div className="xxm-tooltip-row"><span>发生时间</span><b>{point.time}</b></div></div>;
}
