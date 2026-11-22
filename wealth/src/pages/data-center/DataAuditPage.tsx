import { Fragment, useEffect, useRef, useState } from "react";
import {
  completenessLabels, dataAuditApi, updateLabels,
  type AuditDay, type AuditDetail, type AuditRow, type CompletenessStatus, type UpdateStatus,
} from "../../features/data-center/api/dataAuditApi";
import { clientPolicy } from "../../features/data-center/api/clientPolicy";
import { errorMessage } from "../../features/data-center/api/dataCenterApi";
import { Button, Empty, Field, Notice, Pagination, Panel } from "../../features/data-center/ui/primitives";
import { DataCenterShell } from "./DataCenterShell";
import "./data-audit-page.css";

const completenessStates = Object.keys(completenessLabels) as CompletenessStatus[];
const updateStates = Object.keys(updateLabels) as UpdateStatus[];
const PAGE_SIZE = clientPolicy.resultLimit;
const layers: Record<string, string> = { raw: "Raw", silver: "Silver", gold: "Gold", serving: "Serving" };
const timestampFormat = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

function timestamp(value: string | null) {
  return value ? timestampFormat.format(new Date(value)) : "—";
}

function previousShanghaiDay() {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" })
    .format(new Date(Date.now() - 24 * 60 * 60 * 1000));
}

export function DataAuditPage() {
  const [day, setDay] = useState(previousShanghaiDay);
  const [observed, setObserved] = useState<AuditDay>();
  const [requestId, setRequestId] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [completeness, setCompleteness] = useState<CompletenessStatus | "">("");
  const [update, setUpdate] = useState<UpdateStatus | "">("");
  const [page, setPage] = useState(0);
  const [selection, setSelection] = useState<{ key: string; name: string; run: string }>();
  const table = useRef<HTMLDivElement>(null);
  const detailHeading = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    dataAuditApi.day(day, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.state === "unavailable") setError("本机 DG 暂不可用");
      else setObserved(result);
      setLoading(false);
    }).catch((failure: unknown) => {
      if (controller.signal.aborted) return;
      setError(errorMessage(failure));
      setLoading(false);
    });
    return () => controller.abort();
  }, [day, requestId]);

  const result = observed?.business_date === day ? observed : undefined;
  const matched = (result?.rows ?? []).filter((row) =>
    (!update || row.update.status === update) && (!completeness || row.completeness.status === completeness));
  const pageCount = Math.max(1, Math.ceil(matched.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);

  function goToPage(next: number) {
    setPage(next);
    if (table.current) table.current.scrollTop = 0;
  }

  function openDetails(row: AuditRow) {
    if (result?.summary_run_id) setSelection({
      key: row.scope.asset_key, name: row.dataset_name, run: result.summary_run_id,
    });
  }

  return <DataCenterShell audit>
    <header className="dc-title dc-audit-title">
      <div><h1>数据审计</h1><p>查看本机 DG 数据集的每日更新和齐备状态</p></div>
      <Field label="业务日期"><input type="date" value={day} onChange={(event) => {
        if (!event.target.value) return;
        setDay(event.target.value);
        setObserved(undefined);
        setSelection(undefined);
        setLoading(true);
        setError(undefined);
        goToPage(0);
      }} /></Field>
      <Button onClick={() => setRequestId((id) => id + 1)} disabled={loading}>刷新</Button>
    </header>
    {error && <Notice>{error}{result?.generated_at && `，当前显示 ${timestamp(result.generated_at)} 生成的结果。 `}</Notice>}
    {loading && !result && <Empty title="正在读取每日总结…" />}
    {!loading && !error && result?.state === "not_generated" && <Empty title="所选日尚未生成每日总结" />}
    {result?.state === "ready" && result.summary && <>
      <Panel title="每日总结" action={<span className="dc-secondary">生成时间 {timestamp(result.generated_at)}</span>}>
        <div className="dc-audit-metrics">
          {completenessStates.map((status) => <button type="button" key={status} className={`dc-audit-metric ${status}`}
            aria-label={`${completenessLabels[status]} ${result.summary?.[status]}`}
            aria-pressed={completeness === status} onClick={() => {
              setCompleteness(status); setUpdate(""); goToPage(0);
              detailHeading.current?.scrollIntoView?.({ block: "nearest" });
            }}>
            <span>{completenessLabels[status]}</span><strong className="num">{result.summary?.[status]}</strong>
          </button>)}
        </div>
      </Panel>
      <div ref={detailHeading}>
      <Panel title="数据集明细" action={<div className="dc-actions dc-audit-filters">
        <select aria-label="更新状态" value={update} onChange={(event) => {
          setUpdate(event.target.value as UpdateStatus | ""); goToPage(0);
        }}><option value="">全部更新状态</option>{updateStates.map((status) =>
          <option key={status} value={status}>{updateLabels[status]}</option>)}</select>
        <select aria-label="齐备状态" value={completeness} onChange={(event) => {
          setCompleteness(event.target.value as CompletenessStatus | ""); goToPage(0);
        }}><option value="">全部齐备状态</option>{completenessStates.map((status) =>
          <option key={status} value={status}>{completenessLabels[status]}</option>)}</select>
      </div>}>
        {matched.length ? <div ref={table} className="dc-table-scroll dc-audit-table">
          <table className="dc-table">
            <colgroup>{[23, 6, 6, 9, 9, 12, 9, 9, 13, 5].map((width, index) =>
              <col key={index} style={{ width: `${width}%` }} />)}</colgroup>
            <thead><tr>{["数据集", "层", "频度", "适用截至", "更新状态", "齐备状态", "产出时间", "核验时间", "依据 / 原因", "查看"].map((label) =>
              <th key={label} scope="col">{label}</th>)}</tr></thead>
            <tbody>{matched.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map((row) =>
              <Fragment key={row.scope.asset_key}>
                <AuditTableRow row={row} onOpen={() => openDetails(row)} />
                {row.completeness.components.filter((component) =>
                  component.name === "东方财富概念板块" && (!completeness || component.status === completeness)).map((component) =>
                  <AuditTableRow key={component.name} row={row} component={component} onOpen={() => openDetails(row)} />)}
              </Fragment>)}</tbody>
          </table>
        </div> : <Empty title="没有符合筛选条件的数据集" />}
        <Pagination previous={currentPage > 0} next={currentPage + 1 < pageCount}
          onPrevious={() => goToPage(currentPage - 1)} onNext={() => goToPage(currentPage + 1)}>
          {matched.length} 个数据集 · 第 {currentPage + 1} / {pageCount} 页
        </Pagination>
      </Panel>
      </div>
    </>}
    {selection && <Details day={day} assetKey={selection.key} name={selection.name} run={selection.run} onClose={() => setSelection(undefined)} />}
  </DataCenterShell>;
}

function AuditTableRow({ row, component, onOpen }: {
  row: AuditRow; component?: AuditRow["completeness"]["components"][number]; onOpen: () => void;
}) {
  const status = component ?? row.completeness;
  const name = component?.name ?? row.dataset_name;
  const regular = !component && status.status === "complete" && row.scope.coverage_scope === "regular_session";
  return <tr>
    <td>{name}</td><td>{layers[row.layer] ?? row.layer}</td><td>{row.scope.frequency ?? "—"}</td>
    <td className="dc-audit-time">{row.scope.as_of_date ?? "—"}</td>
    <td><span className={`dc-audit-status ${row.update.status}`}>{updateLabels[row.update.status]}</span></td>
    <td><span className={`dc-audit-status ${status.status}`}>{completenessLabels[status.status]}{regular && "（常规时段）"}</span></td>
    <td className="dc-audit-time">{timestamp(row.update.published_at)}</td>
    <td className="dc-audit-time">{timestamp(row.completeness.checked_at)}</td>
    <td className="dc-secondary">{status.reason.message}</td>
    <td><button className="dc-link" type="button" onClick={onOpen} aria-label={`查看${name}`}>查看</button></td>
  </tr>;
}

function Details({ day, assetKey, name, run, onClose }: {
  day: string; assetKey: string; name: string; run: string; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [detail, setDetail] = useState<AuditDetail>();
  const [error, setError] = useState<string>();
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    const controller = new AbortController();
    dataAuditApi.detail(day, assetKey, run, controller.signal).then((value) => {
      if (!controller.signal.aborted) setDetail(value);
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(errorMessage(failure));
    });
    return () => controller.abort();
  }, [day, assetKey, run]);

  return <dialog className="dc-dialog dc-audit-dialog" ref={dialog} aria-labelledby="dc-audit-detail-title" onClose={onClose}>
    <div className="dc-actions"><h2 id="dc-audit-detail-title">{name}</h2><Button onClick={onClose}>关闭</Button></div>
    {error ? <Notice>{error}</Notice> : !detail ? <Empty title="正在读取审计详情…" /> : <>
      <dl className="dc-audit-detail">
        <dt>更新状态</dt><dd>{updateLabels[detail.update.status]} · {detail.update.reason.message}</dd>
        <dt>齐备状态</dt><dd>{completenessLabels[detail.completeness.status]} · {detail.completeness.reason.message}</dd>
        <dt>适用截至</dt><dd>{detail.scope.as_of_date ?? "—"}</dd>
        <dt>频度 / 分区</dt><dd>{detail.scope.frequency ?? "未记录"} / {detail.scope.partition_key ?? "未记录"}</dd>
        <dt>核验范围</dt><dd>{detail.scope.coverage_scope === "regular_session" ? "常规交易时段" : detail.scope.coverage_scope === "listed_sh_sz_etf" ? "当天上市的沪深 ETF" : "该数据集适用范围"}</dd>
        <dt>产出时间 / 核验时间</dt><dd>{timestamp(detail.update.published_at)} / {timestamp(detail.completeness.checked_at)}</dd>
        <dt>应有 / 实际</dt><dd>{detail.completeness.expected_count ?? "—"} / {detail.completeness.actual_count ?? "—"}</dd>
        <dt>缺少 / 多出</dt><dd>{detail.completeness.missing_count ?? "—"} / {detail.completeness.extra_count ?? "—"}</dd>
        <dt>产出版本</dt><dd>{detail.version.target_version ?? "—"}</dd>
        <dt>规则版本</dt><dd>{detail.version.rule_version}</dd>
        {detail.version.inputs.length > 0 && <><dt>输入版本</dt><dd>{detail.version.inputs.map((input) =>
          <div key={input.asset_key}>{input.asset_key} · {input.target_version}</div>)}</dd></>}
      </dl>
      {detail.completeness.components.map((component) => <p key={component.name}>
        {component.name} · {completenessLabels[component.status]} · {component.reason.message}
      </p>)}
      {detail.completeness.evidence.length > 0 && <ul className="dc-audit-evidence">{detail.completeness.evidence.map((item) =>
        <li key={`${item.type}-${item.record_id}`}><a href={`http://127.0.0.1:3000/runs/${encodeURIComponent(item.run_id)}`} target="_blank" rel="noreferrer">
          {item.check_name ?? "DG 产出记录"}{item.passed === undefined ? "" : item.passed ? " · 通过" : " · 未通过"}
        </a>{item.message && <span> · {item.message}</span>}</li>)}</ul>}
      {detail.completeness.samples.length > 0 && <p>差异样本 {JSON.stringify(detail.completeness.samples)}</p>}
      {detail.completeness.exceptions.length > 0 && <p>已采用例外 {JSON.stringify(detail.completeness.exceptions)}</p>}
    </>}
  </dialog>;
}
