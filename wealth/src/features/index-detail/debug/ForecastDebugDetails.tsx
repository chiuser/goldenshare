import type { ForecastDebugResponse } from "../xxm-forecast/types";
export function ForecastDebugDetails({ response }: {
    response: ForecastDebugResponse;
}) {
    const d = response.debug;
    return <details aria-label="关键点预判计算依据"><summary>计算依据</summary><p>截至{response.computedThrough}，目标{response.targetEndpoint ?? "未求解"}；精度{d.precisionPolicy}</p><p>参照选择{d.selectedReference ?? "未求解"}；近参照{d.nearestDecision.status}：{d.nearestDecision.reason ?? "未检查"}；远参照{d.farEvaluated ? "已求解" : "未求解"}</p>
    <p>结果编号{response.forecastId}；来源{d.sourceInputId ?? "无"}；日历{d.calendarInputId ?? "未读取"}</p>
    {(["nearest", "farther"] as const).map(k => { const r = d.references[k]; return r ? <p key={k}>{k}：{r.startTime}—{r.endTime}，价格{r.price}（{r.priceAt}），DIF {r.dif}（{r.difAt}）</p> : null; })}
    {[...d.conditions, ...d.structureFollowConditions].map(c => <div key={c.id}><p>{c.id} · {c.outcome}{"relatedStructureId" in c ? ` · 旧结构${c.relatedStructureId} · ${c.direction}` : ` · ${c.referenceRole}`}</p>
      {"originWave" in c ? <p>原段{c.originWave.start}—{c.originWave.end}，{c.originWave.count}根；收盘极值{c.originWave.price}（{c.originWave.priceAt}），DIF极值{c.originWave.dif}（{c.originWave.difAt}）；下一同色起始{c.nextSameColorStart ?? "尚未"}，{c.nextSameColorCount}根</p> : null}
      {c.priceRanges.length > 0 && <p>适用收盘区间</p>}
      {c.priceRanges.map((r, i) => <p key={i}>收盘{r.lowerInclusive ? "≥" : ">"}{r.lower}{r.upper === null ? "" : ` 且${r.upperInclusive ? "≤" : "<"}${r.upper}`}</p>)}
      <p>必要比较（结果以适用收盘区间为准）</p>
      <pre>{JSON.stringify(c.predicates, null, 2)}</pre>
      {"precisionRanges" in c && c.precisionRanges.length ? <pre>旧结构临界待核：{JSON.stringify(c.precisionRanges, null, 2)}</pre> : null}</div>)}
    {d.precisionRanges.length ? <><p>另有{d.precisionRanges.length}段临界价格待核验，未当作无解。</p><pre>{JSON.stringify(d.precisionRanges, null, 2)}</pre></> : null}
  </details>;
}
