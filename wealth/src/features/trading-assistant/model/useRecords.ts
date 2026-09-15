import { useCallback, useEffect, useRef, useState } from "react";
import { getAuthEpoch } from "../../auth/model/authStorage";
import type { CashRecordsQuery, CashRecordsResponse, ClosedRecordsResponse, RecordsSummary, RoundRecordsScope, TradeDayGroupsResponse, TradeRecordsQuery, TradeRecordsResponse } from "../api/generatedContracts";
import { getCashRecords, getClosedRecords, getRecordsSummary, getTradeDayGroups, getTradeRecords } from "../api/recordsApi";
import { TradingAssistantApiError } from "../api/tradingAssistantApi";
import { getCalculationStatus } from "../api/positionsApi";
import { CALCULATION_READ_POLICY } from "./calculationReadPolicy";
import { defaultRecordFilter, recordListQuery, recordRange, type RecordCategory, type RecordFilter } from "./recordsQuery";

export type RecordPage = { kind: "TRADE"; data: TradeRecordsResponse } | { kind: "DAY"; data: TradeDayGroupsResponse }
  | { kind: "CASH"; data: CashRecordsResponse } | { kind: "CLOSED"; data: ClosedRecordsResponse };
type Reading = { key: string; scopeKey: string; summary: RecordsSummary; page: RecordPage };

/** Summary and page are published together; cursor history lives only within that context. */
export function useRecords(selected: string, category: RecordCategory, filter: RecordFilter, round: RoundRecordsScope | null, revision: number,
  parent?: { token: string; onChanged: () => void }) {
  const [reading, setReading] = useState<Reading | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(true);
  const [reload, setReload] = useState(0);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const summary = useRef<RecordsSummary | null>(null);
  const key = JSON.stringify([selected, category, filter, round, revision, parent?.token, reload, pageIndex]);
  const identity = JSON.stringify([selected, category, filter, round, revision, parent?.token]);
  const scopeKey = JSON.stringify([selected, revision, parent?.token]);
  const lastIdentity = useRef(identity);
  const lastRevision = useRef(revision);
  const lastParentToken = useRef(parent?.token);
  const terminal = useRef(new Set<string>());
  const refresh = useCallback(() => { summary.current = null; setReading(null); setCursors([null]); setPageIndex(0); setReload(v => v + 1); }, []);
  useEffect(() => {
    if (lastParentToken.current !== parent?.token) { lastParentToken.current = parent?.token; summary.current = null; }
    if (lastRevision.current !== revision) { lastRevision.current = revision; summary.current = null; }
    if (identity !== lastIdentity.current) {
      lastIdentity.current = identity; setCursors([null]); setPageIndex(0);
      if (pageIndex !== 0) return;
    }
    const abort = new AbortController(), epoch = getAuthEpoch();
    let active = true;
    const current = () => active && !abort.signal.aborted && epoch === getAuthEpoch();
    setBusy(true); setError(false);
    void (async () => {
      const month = defaultRecordFilter();
      let totals = summary.current;
      // Account and month changes must never reuse another summary's context.
      if (!totals || totals.requestedStartDate !== month.start || totals.requestedEndDate !== month.end
        || totals.scope.accountMode !== (selected === "ALL" ? "ALL" : "SINGLE")
        || (selected !== "ALL" && totals.scope.accounts[0]?.accountId !== selected)) {
        totals = await getRecordsSummary({ ...recordRange(selected, month), ...(parent ? { readContext:parent.token } : {}) }, abort.signal);
      }
      if (!current()) return;
      const query = recordListQuery(selected, category, filter, totals.readContext.contextToken, cursors[pageIndex] ?? null);
      const page: RecordPage = category === "CASH" ? { kind: "CASH", data: await getCashRecords(query as CashRecordsQuery, abort.signal) }
        : category === "DAY" ? { kind: "DAY", data: await getTradeDayGroups(query as TradeRecordsQuery, abort.signal) }
          : category === "CLOSED" ? { kind: "CLOSED", data: await getClosedRecords(round ? { ...round, readContext: totals.readContext.contextToken, limit: 20, cursor: cursors[pageIndex] } : query as TradeRecordsQuery, abort.signal) }
            : { kind: "TRADE", data: await getTradeRecords(query as TradeRecordsQuery, abort.signal) };
      if (current()) { summary.current = totals; setReading({ key, scopeKey, summary: totals, page }); }
    })().catch(reason => {
      if (!current()) return;
      if (reason instanceof TradingAssistantApiError && reason.details.code === "TA_READ_CONTEXT_CHANGED") { if (parent) parent.onChanged(); else refresh(); }
      else { setReading(null); setError(true); }
    }).finally(() => { if (current()) setBusy(false); });
    const visibility = () => { if (document.visibilityState === "hidden") { active = false; abort.abort(); } else refresh(); };
    document.addEventListener("visibilitychange", visibility);
    return () => { active = false; abort.abort(); document.removeEventListener("visibilitychange", visibility); };
  }, [key]); // key includes every applied selection and page identity
  useEffect(() => {
    if (!reading || reading.key !== key) return;
    const waiting = reading.summary.closedTradeCount === null;
    const pending = reading.page.data.coverage.accounts.filter(a => waiting || ["Recalculating", "Delayed", "Partial"].includes(a.dataStatus));
    const refs = reading.summary.readContext.accounts;
    const token = reading.summary.readContext.contextToken;
    const ids = pending.map(a => a.accountId).filter(id => !terminal.current.has(`${token}:${id}`));
    if (!ids.length) return;
    const abort = new AbortController(), epoch = getAuthEpoch();
    let timer: ReturnType<typeof setTimeout>;
    const visibility = () => { if (document.visibilityState === "hidden") { abort.abort(); clearTimeout(timer); } };
    document.addEventListener("visibilitychange", visibility);
    const due = new Map(ids.map(id => [id, Date.now() + CALCULATION_READ_POLICY.activeDelayMs]));
    const schedule = () => { if (due.size) timer = setTimeout(check, Math.max(0, Math.min(...due.values()) - Date.now())); };
    async function check() {
      try {
        for (const [id, at] of due) {
          if (abort.signal.aborted || epoch !== getAuthEpoch() || document.visibilityState === "hidden") return;
          if (at > Date.now()) continue;
          const status = await getCalculationStatus(id, abort.signal);
          if (abort.signal.aborted || epoch !== getAuthEpoch()) return;
          if (status.stage === "PUBLISHED" || status.stage === "FAILED") {
            terminal.current.add(`${token}:${id}`); refresh(); return;
          }
          if (status.calculationTargetVersion !== refs.find(r => r.accountId === id)?.calculationTargetVersion) { refresh(); return; }
          due.set(id, Date.now() + (status.stage === "WAITING_DATA" ? CALCULATION_READ_POLICY.waitingDataDelayMs : CALCULATION_READ_POLICY.activeDelayMs));
        }
        schedule();
      } catch { if (!abort.signal.aborted && epoch === getAuthEpoch()) setError(true); }
    }
    schedule();
    return () => { abort.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", visibility); };
  }, [reading, key, refresh]);
  const visible = reading?.key === key ? reading : null;
  return { summary: reading?.scopeKey === scopeKey ? reading.summary : null, page: visible?.page ?? null, error, busy, pageIndex, refresh,
    previous: () => { if (!busy && pageIndex > 0) setPageIndex(v => v - 1); },
    next: () => { const cursor = visible?.page.data.nextCursor; if (!busy && cursor) { setCursors(v => [...v.slice(0, pageIndex + 1), cursor]); setPageIndex(v => v + 1); } },
  };
}
