import { useCallback, useEffect, useRef, useState } from "react";
import { dataCenterApi } from "../api/dataCenterApi";
import type { Phase } from "../api/contracts";
import { phaseText, timeText } from "../model/presentation";
import { useObserver } from "../model/useObserver";
import { Button, Empty, Notice, Pagination, Panel } from "./primitives";
export function HistoryPanel({ revision, onSelect }: { revision: number; onSelect: (id: string) => void }) {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [latestRequest, setLatestRequest] = useState(0);
  const selectedLatest = useRef(0);
  const read = useCallback(async (s: AbortSignal) => ({ ...await dataCenterApi.history(cursors.at(-1), s), latestRequest }), [cursors, revision, latestRequest]);
  const h = useObserver(read);
  useEffect(() => {
    if (latestRequest > selectedLatest.current && h.value?.latestRequest === latestRequest && cursors.length === 1) {
      selectedLatest.current = latestRequest;
      if (h.value.items[0]) onSelect(h.value.items[0].runId);
    }
  }, [latestRequest, h.value, cursors.length, onSelect]);
  return <Panel title="历史任务" action={<Button disabled={h.loading} onClick={() => { setLatestRequest(v => v + 1); setCursors([null]); }}>查看最近任务</Button>}>
    {h.error && <Notice>{h.error}<Button onClick={h.refresh}>重新读取</Button></Notice>}
    {!h.value && !h.error && <Empty title="正在读取历史任务…" />}
    {h.value?.items.length === 0 && <Empty title="暂无历史任务" />}
    {!!h.value?.items.length && <div className="dc-table-scroll"><table className="dc-table dc-history"><colgroup><col /><col /><col /><col /><col /><col /></colgroup><thead><tr>{["开始时间", "公告日期范围", "结果", "成功 / 复用 / 失败", "补充信息", "操作"].map(v => <th key={v}>{v}</th>)}</tr></thead><tbody>{h.value.items.map(r => <tr key={r.runId}>
      <td className="num">{timeText(r.createdAt)}</td><td className="num">{r.startDate ?? "—"} — {r.endDate ?? "—"}</td><td>{phaseText[r.phase as Phase] ?? "状态暂不可确认"}</td><td className="num">{r.succeeded} / {r.reused} / {r.failed}</td><td>{r.retryOfRunId ? "关联重试批次" : "原日期任务"}</td><td><button type="button" className="dc-link" onClick={() => onSelect(r.runId)}>查看详情</button></td></tr>)}</tbody></table></div>}
    <Pagination previous={cursors.length > 1} next={!!h.value?.nextCursor} disabled={h.loading} onPrevious={() => setCursors(c => c.slice(0, -1))} onNext={() => setCursors(c => [...c, h.value!.nextCursor])}>第 {cursors.length} 页 · 每页最多 20 个任务</Pagination>
  </Panel>;
}
