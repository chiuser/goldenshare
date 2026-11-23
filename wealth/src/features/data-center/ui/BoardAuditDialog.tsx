import { useEffect, useRef, useState, type MouseEvent } from "react";
import {
  dataAuditApi, DC_CLASSIFICATION_RAW, type AuditBoard, type AuditBoardReview, type AuditBoardRun,
  type AuditBoardSourceResult, type AuditRow, updateLabels,
} from "../api/dataAuditApi";
import { clientPolicy } from "../api/clientPolicy";
import { DataCenterApiError, errorMessage } from "../api/dataCenterApi";
import { timeText } from "../model/presentation";
import { Button, Empty, Metrics, Notice } from "./primitives";

type Operation = { kind: "recheck" | "confirm"; runId: string; deadline: number; retryRunId?: string };
const activeStatuses = new Set(["QUEUED", "NOT_STARTED", "STARTING", "STARTED", "SUSPENDED", "CANCELING"]);
const concepts = (boards: AuditBoard[]) => boards.filter(({ category }) => category === "概念板块");
const sourceFailed = ({ status }: AuditBoardSourceResult) => status === "failed";

function sourceText(result: AuditBoardSourceResult, member: boolean) {
  switch (result.status) {
    case "success": return member && result.count != null ? `返回 ${result.count} 条成分` : result.board?.name ?? "已返回";
    case "not_returned": return member ? "本次成分为空" : "源端本次未返回";
    case "failed": return result.message || "核查失败";
  }
}

export function BoardAuditDialog({ day, row, canOperate, onClose, onConfirmed }: {
  day: string; row: AuditRow; canOperate: boolean; onClose: () => void; onConfirmed: () => void;
}) {
  const assetKey = row.scope.asset_key;
  const raw = assetKey === DC_CLASSIFICATION_RAW;
  const dialog = useRef<HTMLDialogElement>(null);
  const action = useRef<AbortController | null>(null);
  const [review, setReview] = useState<AuditBoardReview>();
  const [reading, setReading] = useState(true);
  const [error, setError] = useState<string>();
  const [needsRead, setNeedsRead] = useState(false);
  const [busy, setBusy] = useState<Pick<Operation, "kind" | "retryRunId">>();
  const [unobserved, setUnobserved] = useState<Operation>();
  const [shown, setShown] = useState<"reference" | "standard">();

  useEffect(() => {
    const modal = dialog.current!;
    const opener = document.activeElement as HTMLElement | null;
    modal.showModal();
    return () => {
      action.current?.abort();
      modal.close();
      opener?.focus();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    dataAuditApi.boardStandard(day, assetKey, controller.signal).then((value) => {
      if (!controller.signal.aborted) setReview(value);
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(errorMessage(failure));
    }).finally(() => {
      if (!controller.signal.aborted) setReading(false);
    });
    return () => controller.abort();
  }, [day, assetKey]);

  const allowed = raw && canOperate && review?.can_operate !== false;
  const editable = allowed && review?.review_version && !review.standard && !needsRead && !unobserved;
  const reference = review?.reference;
  const standard = review?.standard;
  const recheck = review?.recheck;
  const added = review ? concepts(review.added) : [];
  const removed = review ? concepts(review.removed) : [];
  const differences = [...added.map((board) => ({ ...board, added: true })), ...removed.map((board) => ({ ...board, added: false }))];
  const fixedDifferences = review ? [
    ...review.added.map((board) => ({ ...board, added: true })),
    ...review.removed.map((board) => ({ ...board, added: false })),
  ].filter(({ category }) => category === "行业板块" || category === "地域板块") : [];
  const sourceByCode = new Map(recheck?.results.map((result) => [result.code, result]));
  const gap = recheck?.has_confirmed_gap === true;
  const failedBoards = recheck?.results.filter(({ classification, member }) => sourceFailed(classification) || sourceFailed(member)).length ?? 0;
  const retryId = failedBoards ? recheck?.run_id : undefined;
  const viewed = shown === "reference" ? reference : standard;

  function close() { if (!busy) onClose(); }

  async function readAgain() {
    if (action.current) return;
    const controller = new AbortController();
    action.current = controller;
    setReading(true);
    setError(undefined);
    try {
      const next = await dataAuditApi.boardStandard(day, assetKey, controller.signal);
      if (!controller.signal.aborted) {
        setReview(next);
        setNeedsRead(false);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(errorMessage(failure));
    } finally {
      action.current = null;
      if (!controller.signal.aborted) setReading(false);
    }
  }

  async function operate(kind: Operation["kind"], retryRunId?: string) {
    if (action.current || !review?.review_version) return;
    const controller = new AbortController();
    action.current = controller;
    const { signal } = controller;
    setBusy({ kind, retryRunId: unobserved?.retryRunId ?? retryRunId });
    setError(undefined);
    let operation = unobserved;
    let terminal = false;
    let deadline = operation?.deadline ?? Infinity;
    try {
      const version = review.review_version;
      let run: AuditBoardRun | undefined;
      if (!operation) {
        run = kind === "confirm" ? await dataAuditApi.boardConfirm(day, version, signal)
          : await dataAuditApi.boardRecheck(day, version, retryRunId, signal);
        deadline = run.deadline ? Date.parse(run.deadline) : Infinity;
        operation = { kind, runId: run.run_id, deadline, retryRunId };
      }
      const pollMs = clientPolicy.defaultPollSeconds * 1000;
      let waitMs = run ? pollMs : 0;
      while (!signal.aborted && (!run || activeStatuses.has(run.status.toUpperCase()))) {
        if (waitMs) {
          await new Promise((resolve) => window.setTimeout(resolve, Math.min(Math.max(0, deadline - Date.now()), waitMs)));
        }
        if (signal.aborted) return;
        const remaining = deadline - Date.now();
        if (waitMs && remaining <= 0) throw new Error("核查已到截止时间，请重新读取任务状态");
        const readSignal = remaining > 0 && remaining < clientPolicy.requestSeconds * 1000
          ? AbortSignal.any([signal, AbortSignal.timeout(remaining)]) : signal;
        try {
          run = await dataAuditApi.boardRun(operation.runId, readSignal);
          waitMs = pollMs;
        } catch (failure) {
          const transient = !(failure instanceof DataCenterApiError) || failure.status === 503;
          if (!transient || operation.kind !== "recheck" || !Number.isFinite(deadline)) throw failure;
          waitMs = clientPolicy.readRetrySeconds * 1000;
        }
      }
      if (signal.aborted || !run) return;
      terminal = true;
      setUnobserved(undefined);
      const result = run.result && "has_confirmed_gap" in run.result && run.result.review_version === version
        ? { ...run.result, run_id: run.run_id } : undefined;
      if (result) setReview({ ...review, recheck: result });
      const succeeded = run.status.toUpperCase() === "SUCCESS";
      if (succeeded && kind === "confirm") onConfirmed();
      setNeedsRead(true);
      const next = await dataAuditApi.boardStandard(day, assetKey, signal);
      if (signal.aborted) return;
      const latestResult = next.review_version === version ? result ?? next.recheck : next.recheck;
      setReview({ ...next, recheck: latestResult });
      setNeedsRead(false);
      if (!succeeded) {
        setError(run.error?.message || (["TIMEOUT", "TIMED_OUT"].includes(run.status.toUpperCase()) ? "核查超时"
          : kind === "recheck" ? "核查失败" : "确认失败"));
      }
    } catch (failure) {
      if (signal.aborted) return;
      if (!terminal && operation) setUnobserved(operation);
      if (failure instanceof DataCenterApiError && failure.status === 409) setNeedsRead(true);
      setError(!terminal && Date.now() >= deadline ? "核查已到截止时间，请重新读取任务状态" : errorMessage(failure));
    } finally {
      action.current = null;
      if (!signal.aborted) setBusy(undefined);
    }
  }

  return <dialog ref={dialog} className="dc-dialog dc-audit-dialog dc-board-audit"
    aria-labelledby="dc-board-audit-title"
    onCancel={(event) => { event.preventDefault(); close(); }}
    onClick={(event: MouseEvent<HTMLDialogElement>) => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right
        || event.clientY < bounds.top || event.clientY > bounds.bottom) close();
    }}>
    <div className="dc-actions dc-board-heading">
      <div><h2 id="dc-board-audit-title">东方财富概念板块名单核查</h2>
        <p>东方财富板块分类 · {raw ? "Raw" : "Silver"}</p></div>
      <Button disabled={!!busy} onClick={close}>关闭</Button>
    </div>
    {error && <Notice>{error}</Notice>}
    {reading && <Empty title="正在读取板块标准集…" />}
    {!reading && error && (!review || needsRead) && <Button onClick={() => void readAgain()}>重新读取</Button>}
    {review && <>
      <div className="dc-board-meta"><span>业务日期 <strong className="num">{day}</strong></span>
        <span className={`dc-audit-status ${row.update.status}`}>{updateLabels[row.update.status]}</span>
        {gap && <span className="dc-audit-status gap">已确认缺口</span>}
        {!gap && !standard && review.reason === "manual_review" && <span className="dc-audit-status pending">需要人工核查</span>}
      </div>
      {!reference && review.state === "reference_missing" && <Notice>参照标准集缺失</Notice>}
      {gap && <Notice>源端有，本地缺少。请补齐当天数据，再核对新产出。</Notice>}
      {busy && <div className="dc-board-progress" role="status">
        <span className="dc-board-spinner" aria-hidden="true" />
        <div>{busy.kind === "recheck" ? "正在核查 Tushare" : "正在生成标准集"}
          {busy.kind === "recheck" && <p>业务日期 {day} · {busy.retryRunId ? `重试 ${failedBoards} 个板块的失败项` : `本地差异范围 ${differences.length} 个板块`}</p>}</div>
      </div>}
      {shown && viewed ? <section>
        <h3>{shown === "reference" ? "参照标准集" : "当日标准集"} · {viewed.business_date}</h3>
        <p>版本 {viewed.version}</p>
        <div className="dc-table-scroll"><table className="dc-table">
          <thead><tr><th scope="col">板块名称</th><th scope="col">板块代码</th></tr></thead>
          <tbody>{concepts(viewed.boards).map((board) => <tr key={board.code}><td>{board.name}</td><td>{board.code}</td></tr>)}</tbody>
        </table></div>
        <Button onClick={() => setShown(undefined)}>返回名单核查</Button>
      </section> : <>
        <dl className="dc-audit-detail">
          <dt>参照标准集</dt><dd>{reference?.business_date ?? "未记录"}</dd>
          <dt>当日产出</dt><dd>{timeText(row.update.published_at)}</dd>
          <dt>当日标准集</dt><dd>{standard?.business_date ?? "待确认"}</dd>
          {recheck?.checked_at && <><dt>源端核查时间</dt><dd>{timeText(recheck.checked_at)}</dd></>}
        </dl>
        <Metrics items={[
          ["参照名单", reference ? concepts(reference.boards).length : null],
          ["当天名单", review.review_version || review.current.length ? concepts(review.current).length : null],
          ["新增", review.review_version ? added.length : null, "dc-info"],
          ["减少", review.review_version ? removed.length : null, "dc-danger"],
        ]} />
        <h3>新增和减少</h3>
        {differences.length ? <div className="dc-table-scroll"><table className="dc-table">
          <thead><tr>{["板块名称", "板块代码", "变更", "参照名单", "当天名单",
            ...(recheck ? ["Tushare 分类", "Tushare 成分"] : [])].map((name) => <th scope="col" key={name}>{name}</th>)}</tr></thead>
          <tbody>{differences.map((board) => {
            const source = sourceByCode.get(board.code);
            return <tr key={board.code}>
              <td>{board.name}</td><td>{board.code}</td>
              <td className={board.added ? "dc-info" : "dc-danger"}>{board.added ? "新增" : "减少"}</td>
              <td>{board.added ? "—" : "有"}</td><td>{board.added ? "有" : "—"}</td>
              {recheck && <>
                <td title={source?.classification.checked_at ? timeText(source.classification.checked_at) : undefined}>
                  {source?.confirmed_gap ? "源端有，本地缺少" : source ? sourceText(source.classification, false) : "未核查"}</td>
                <td title={source?.member.checked_at ? timeText(source.member.checked_at) : undefined}>
                  {source ? sourceText(source.member, true) : "未核查"}</td>
              </>}
            </tr>;
          })}</tbody>
        </table></div> : <Empty title={!review.review_version ? "暂无名单差异可供核查"
          : fixedDifferences.length ? "无概念板块增减" : "无名单增减"} />}
        {fixedDifferences.length > 0 && <section>
          <h3 id="dc-board-fixed-differences">行业和地域板块变动</h3>
          <div className="dc-table-scroll"><table className="dc-table" aria-labelledby="dc-board-fixed-differences">
            <thead><tr><th scope="col">类别</th><th scope="col">板块代码</th><th scope="col">板块名称</th><th scope="col">变更</th></tr></thead>
            <tbody>{fixedDifferences.map((board) => <tr key={`${board.category}-${board.code}`}>
              <td>{board.category}</td><td>{board.code}</td><td>{board.name}</td>
              <td className={board.added ? "dc-info" : "dc-danger"}>{board.added ? "新增" : "减少"}</td>
            </tr>)}</tbody>
          </table></div>
        </section>}
        <div className="dc-actions dc-board-footer">
          <Button disabled={!!busy || !reference} onClick={() => setShown("reference")}>查看参照标准集</Button>
          {standard && <Button disabled={!!busy} onClick={() => setShown("standard")}>查看当日标准集</Button>}
          <div className="dc-actions">
            {allowed && unobserved && <Button disabled={!!busy} onClick={() => void operate(unobserved.kind)}>重新读取任务状态</Button>}
            {allowed && !standard && <>
              <Button disabled={!!busy || !editable || !differences.length} onClick={() => void operate("recheck", retryId)}>
                {retryId ? "重试失败项" : "核查 Tushare"}
              </Button>
              <Button disabled={!!busy} onClick={close}>取消</Button>
              <Button tone="primary" disabled={!!busy || !editable || !review.can_confirm || gap}
                onClick={() => void operate("confirm")}>确认并生成标准集</Button>
            </>}
          </div>
        </div>
      </>}
    </>}
  </dialog>;
}
