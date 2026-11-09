import type { XxmLayerState, XxmReference } from "../xxm/types";
const ref = (r: XxmReference) => `${r.startTime}—${r.endTime}；价${r.price}（${r.priceAt}）；DIF ${r.dif}（${r.difAt}）`;
export function XxmDebugDetails({ layer, time }: {
    layer: XxmLayerState;
    time: string;
}) {
    const detail = layer.data?.byTime.get(time)?.debugDetail;
    const response = layer.data?.response;
    if (!detail || !response || !("source" in response))
        return null;
    return <div className="xxm-tooltip" aria-label="顶底识别核验依据"><div className="xxm-tooltip-title">计算依据 · 截至{response.source.computedThrough}</div>
    {detail.point.activeReference ? <p>活动参照：{ref(detail.point.activeReference)}</p> : null}
    {detail.events.map(e => <p key={e.id}>{e.id} · {e.route} · 原状态{e.fromState} · 参照{ref(e.eventReference)} · 结构{e.relatedStructureId ?? "无"}</p>)}
    {detail.structures.map(s => <div key={s.id}><p>结构{s.id} · {s.direction} · 截至请求时点的记录：{s.status}</p><p>形成{s.formedAt}；首次反色{s.firstOppositeAt ?? "尚未"}；下一同色起始{s.nextSameColorStart ?? "尚未"}，有色{s.nextSameColorCount}根</p><p>原参照{ref(s.originalReference)}；形成价格{s.priceExtreme}（{s.priceExtremeAt}）</p>{s.originWave ? <p>原色段完整收盘极值{s.originWave.price}（{s.originWave.priceAt}）；DIF极值{s.originWave.dif}（{s.originWave.difAt}）</p> : null}<p>跟踪价格极值{s.trackingPriceExtreme ?? "尚未"}（{s.trackingPriceExtremeAt ?? "尚未"}）；停止{s.trackingEndedAt ?? "仍在跟踪"}；消失{s.disappearedAt ?? "无"}；原因{s.disappearanceReason ?? "无"}</p></div>)}
  </div>;
}
