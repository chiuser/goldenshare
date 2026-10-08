import type { Context } from "../api/contracts";
import { clientPolicy } from "../api/clientPolicy";
import { useAnnouncementQuery } from "../model/useAnnouncementQuery";
import { numberText, sourceLink } from "../model/presentation";
import { CompanySearch } from "./CompanySearch";
import { Button, Empty, Field, Notice, Pagination, Panel } from "./primitives";
export function QueryPanel({ context, refreshContext }: { context: Context; refreshContext: () => void }) {
  const q = useAnnouncementQuery(context); const r = q.result;
  return <>
    <section className="dc-panel"><div className="dc-query-fields">
      <Field label="公司名称 / 代码 / 首字母"><CompanySearch text={q.companyText} selected={q.selected} dates={q.draft} onText={q.setCompanyText} onSelect={q.chooseCompany} /></Field>
      <Field label="标题关键词"><input aria-label="标题关键词" maxLength={clientPolicy.titleLimit} placeholder="输入公告标题关键词" value={q.draft.titleKeyword} onChange={e => q.setDraft({ ...q.draft, titleKeyword: e.target.value })} /></Field>
      <Field label="公告开始日期"><input aria-label="公告开始日期" type="date" value={q.draft.startDate} onChange={e => q.setDraft({ ...q.draft, startDate: e.target.value })} /></Field>
      <Field label="公告结束日期"><input aria-label="公告结束日期" type="date" value={q.draft.endDate} onChange={e => q.setDraft({ ...q.draft, endDate: e.target.value })} /></Field>
      <Field label="下载状态"><select aria-label="下载状态" value={q.draft.downloadStatus} onChange={e => q.setDraft({ ...q.draft, downloadStatus: e.target.value as typeof q.draft.downloadStatus })}>
        <option value="all">全部</option><option value="downloaded" disabled={context.archiveAvailability !== "ready"}>已下载</option><option value="undownloaded" disabled={context.archiveAvailability !== "ready"}>未下载</option>
      </select></Field>
    </div><div className="dc-actions"><p className="dc-secondary">按公告日期倒序 · 标题匹配原文 · 查询不影响下载范围</p>
      <Button tone="primary" disabled={q.busy} onClick={q.submit}>查询</Button><Button disabled={q.busy} onClick={q.reset}>重置</Button><Button disabled={q.busy} onClick={() => { q.refresh(); refreshContext(); }}>刷新列表</Button>
    </div>{q.error && <Notice>{q.error}</Notice>}</section>
    <Panel title="公告列表" description={r?.total != null ? `共 ${numberText(r.total)} 条公告${q.applied.tsCode ? ` · ${q.applied.tsCode}` : ""}` : "暂无法确认公告数量及更新状态"}>
      {q.loading && !r && <Empty title="正在读取公告列表…" />}
      {r?.pageState.status === "preparing" && !q.readError && <Empty title="正在准备公告列表">{r.preparation?.stage === "checkingStatus" ? `已检查 ${numberText(r.preparation.artifactsChecked)} 个文件 · ` : ""}已读取 {r.preparation?.datesScanned} / {r.preparation?.datesTotal} 个公告日期 · {numberText(r.preparation?.recordsScanned ?? null)} 条公告记录</Empty>}
      {r?.pageState.status === "error" && <Notice>{r.pageState.message ?? "本地公告来源暂不可用"}</Notice>}
      {(r?.pageState.status === "ready" || r?.pageState.status === "empty") && r.pageState.message && <Notice danger={false}>{r.pageState.message}</Notice>}
      {((!r && !q.loading && q.error) || r?.pageState.status === "error" || (q.readError && r?.pageState.status === "preparing")) && <><Empty title="列表暂不可获取">已保留筛选条件；当前公告数量及下载状态无法确认。</Empty><Button tone="primary" disabled={q.busy} onClick={q.refresh}>重新读取</Button></>}
      {r?.pageState.status === "empty" && <><Empty title="没有符合条件的公告">尝试调整日期、公司或标题关键词。</Empty><Button onClick={q.reset}>清除筛选</Button></>}
      {r?.pageState.status === "ready" && <>
        {!r.downloadStatusAvailable && <Notice>下载状态暂无法核验。请连接外盘后刷新；当前状态不代表未下载。</Notice>}
        {q.loading && <p className="dc-secondary" role="status">正在读取…</p>}
        <div className="dc-table-scroll"><table className="dc-table dc-announcements"><colgroup><col /><col /><col /><col /><col /><col /></colgroup><thead><tr>{["公告日期", "公司代码", "公司名称", "标题", "URL", "下载状态"].map(v => <th key={v}>{v}</th>)}</tr></thead>
          <tbody>{r.items.map(row => <tr key={row.recordKey}><td className="num">{row.annDate}</td><td className="num">{row.tsCode ?? "—"}</td><td title={row.companyNameSource === "code" ? "暂无公司名称，使用代码展示" : undefined}>{row.companyName}</td>
            <td><span className="dc-truncate" title={row.title ?? undefined}>{row.title || "—"}</span></td><td>{sourceLink(row.sourceUrl) ? <a href={sourceLink(row.sourceUrl)!} target="_blank" rel="noopener noreferrer">公告详情 ↗</a> : <span className="muted" title={row.sourceUrl ? "公告链接不可安全打开" : "无公告链接"}>—</span>}</td>
            <td><span className={row.downloadStatus === "downloaded" ? "dc-info" : "muted"}>{row.downloadStatus === null ? "—" : row.downloadStatus === "downloaded" ? "已下载" : "未下载"}</span></td></tr>)}</tbody>
        </table></div>
        <Pagination previous={r.hasPrevious} next={r.hasNext} disabled={q.loading} onPrevious={() => q.page(r.page - 1)} onNext={() => q.page(r.page + 1)}>
          显示 {numberText((r.page - 1) * r.pageSize + 1)}—{numberText((r.page - 1) * r.pageSize + r.items.length)} 条 · {r.page} / {r.total == null ? "—" : Math.ceil(r.total / r.pageSize)} 页
        </Pagination>
      </>}
    </Panel>
  </>;
}
