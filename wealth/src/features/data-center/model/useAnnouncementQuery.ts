import { useCallback, useEffect, useRef, useState } from "react";
import type { Company, Conditions, Context, QueryResult } from "../api/contracts";
import { dataCenterApi, errorMessage } from "../api/dataCenterApi";
import { dateError } from "./presentation";
import { useObserver } from "./useObserver";
export function useAnnouncementQuery(context: Context) {
  const defaults = () => ({ ...context.queryDefaults, tsCode: null, titleKeyword: "" });
  const [draft, setDraft] = useState<Conditions>(defaults);
  const [companyText, setCompanyText] = useState("");
  const [selected, setSelected] = useState<Company | null>(null);
  const [applied, setApplied] = useState<Conditions>(defaults);
  const [seed, setSeed] = useState<QueryResult | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  const seedId = seed?.queryId;
  const read = useCallback((s: AbortSignal) => dataCenterApi.query(seedId!, page, s), [seedId, page]);
  const observed = useObserver(seedId ? read : null, r => r.pageState.status === "preparing", context.policy.pollSeconds);
  const result = seed ? (observed.value?.queryId === seed.queryId && observed.value.page === page ? observed.value : seed) : null;
  async function execute(conditions: Conditions) {
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    setBusy(true); setError(null); setSeed(null); setPage(1);
    try {
      const response = await dataCenterApi.createQuery(conditions, controller.signal);
      if (controller.signal.aborted) return;
      setApplied(response.conditions); setSeed(response);
    } catch (e) { if (!controller.signal.aborted) setError(errorMessage(e)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  useEffect(() => { void execute(defaults()); return () => active.current?.abort(); }, []); // context defaults pinned to this page visit
  function submit() {
    if (companyText.trim() && !selected) { setError("请先选择公司"); return; }
    const problem = dateError(draft.startDate, draft.endDate);
    if (problem) { setError(problem); return; }
    void execute({ ...draft, tsCode: selected?.tsCode ?? null, titleKeyword: draft.titleKeyword.trim() });
  }
  function reset() { setDraft(defaults()); setSelected(null); setCompanyText(""); void execute(defaults()); }
  function changeDraft(next: Conditions) {
    if (next.startDate !== draft.startDate || next.endDate !== draft.endDate) { setSelected(null); setCompanyText(""); }
    setDraft(next);
  }
  return { draft, setDraft: changeDraft, companyText, selected, setCompanyText: (text: string) => { setCompanyText(text); setSelected(null); },
    chooseCompany: (c: Company) => { setSelected(c); setCompanyText(`${c.name} · ${c.tsCode}`); },
    applied, result, readError: observed.error, error: error ?? observed.error, busy, loading: busy || observed.loading,
    submit, reset, refresh: () => void execute(applied), page: (p: number) => { setPage(p); } };
}
