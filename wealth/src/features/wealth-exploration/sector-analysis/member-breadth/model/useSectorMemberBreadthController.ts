import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { buildSectorMemberBreadthDetailsViewModel, buildSectorMemberBreadthMetaViewModel, buildSectorMemberBreadthRankingsViewModel } from "../api/sectorMemberBreadthAdapter";
import { fetchSectorMemberBreadthDetails, fetchSectorMemberBreadthMeta, fetchSectorMemberBreadthRankings, SectorMemberBreadthApiError } from "../api/sectorMemberBreadthApi";
import { buildSectorMemberBreadthSearch, parseSectorMemberBreadthUrlState } from "./sectorMemberBreadthUrlState";
import type {
  SectorHierarchyNode,
  SectorMemberBreadthDetailsRequest,
  SectorMemberBreadthDetailsState,
  SectorMemberBreadthDirection,
  SectorMemberBreadthHistoryRange,
  SectorMemberBreadthMaPeriod,
  SectorMemberBreadthMetaViewModel,
  SectorMemberBreadthMetric,
  SectorMemberBreadthRankingRow,
  SectorMemberBreadthRankingsRequest,
  SectorMemberBreadthRankingsViewModel,
  SectorMemberBreadthScope,
  SectorMemberBreadthUrlDirection,
  SectorMemberBreadthUrlMetric,
  SectorMemberBreadthUrlScope,
  SectorMemberBreadthUrlState,
  SectorMemberBreadthViewState,
} from "./sectorMemberBreadthTypes";

const FETCH_TIMEOUT_MS = 5000;
type NavigateSearch = (search: string, options?: { replace?: boolean }) => void;
interface Input { enabled: boolean; search: string; onNavigateSearch: NavigateSearch; }
type MetaState = { kind: "idle" | "loading" } | { kind: "ready"; key: string; data: SectorMemberBreadthMetaViewModel } | { kind: "error"; message: string; retryable: boolean };
type RankingsState = { kind: "idle" | "loading" } | { kind: "ready"; key: string; data: SectorMemberBreadthRankingsViewModel } | { kind: "empty"; key: string; message: string } | { kind: "error"; key: string; message: string; retryable: boolean };

export function useSectorMemberBreadthController({ enabled, search, onNavigateSearch }: Input) {
  const parsed = useMemo(() => parseSectorMemberBreadthUrlState(search), [search]);
  const urlState = parsed.ok ? parsed.value : null;
  const [metaState, setMetaState] = useState<MetaState>({ kind: "idle" });
  const [rankingsState, setRankingsState] = useState<RankingsState>({ kind: "idle" });
  const [detailsState, setDetailsState] = useState<SectorMemberBreadthDetailsState>({ kind: "idle" });
  const [metaRetry, setMetaRetry] = useState(0); const [rankingsRetry, setRankingsRetry] = useState(0); const [detailsRetry, setDetailsRetry] = useState(0);
  const metaId = useRef(0); const rankingsId = useRef(0); const detailsId = useRef(0);
  const activeMetaKey = useRef(""); const activeRankingsKey = useRef(""); const activeDetailsKey = useRef("");
  const acceptedRankingsKey = useRef(""); const acceptedDetailsKey = useRef("");
  const mismatchReloadAttempted = useRef(false);
  const pendingUrlState = useRef<SectorMemberBreadthUrlState | null>(urlState);

  const metaKey = urlState?.market ?? ""; activeMetaKey.current = metaKey;
  useEffect(() => {
    if (!enabled || !urlState) { invalidateAll(); setMetaState({ kind: "idle" }); setRankingsState({ kind: "idle" }); setDetailsState({ kind: "idle" }); return; }
    const key = metaKey; const requestId = ++metaId.current; const abort = new AbortController(); let timedOut = false;
    const timer = window.setTimeout(() => { timedOut = true; abort.abort(); }, FETCH_TIMEOUT_MS);
    setMetaState({ kind: "loading" }); acceptedRankingsKey.current = ""; acceptedDetailsKey.current = ""; setRankingsState({ kind: "idle" }); setDetailsState({ kind: "idle" });
    fetchSectorMemberBreadthMeta(urlState.market, { signal: abort.signal }).then((payload) => {
      if (metaId.current !== requestId || activeMetaKey.current !== key) return;
      setMetaState({ kind: "ready", key, data: buildSectorMemberBreadthMetaViewModel(payload) });
    }).catch((error) => {
      if (metaId.current !== requestId || activeMetaKey.current !== key || (isAbort(error, abort.signal) && !timedOut)) return;
      setMetaState(toError(error, "成员广度基础信息加载失败。"));
    }).finally(() => window.clearTimeout(timer));
    return () => { abort.abort(); window.clearTimeout(timer); };
  // Request identity and explicit retry are the only Meta triggers.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, metaKey, metaRetry, urlState?.market]);

  const resolved = useMemo(() => {
    if (!urlState || metaState.kind !== "ready" || metaState.key !== metaKey) return null;
    return normalizeState(urlState, metaState.data);
  }, [metaKey, metaState, urlState]);

  useEffect(() => {
    if (!resolved || resolved.error) return;
    const canonical = buildSectorMemberBreadthSearch(resolved.state);
    if (canonical !== normalizeSearch(search)) onNavigateSearch(canonical, { replace: true });
  }, [onNavigateSearch, resolved, search]);

  const rankingsRequest = useMemo(() => resolved && !resolved.error && resolved.actualDate ? buildRankingsRequest(resolved.state, resolved.actualDate, resolved.meta) : null, [resolved]);
  const rankingsKey = rankingsRequest ? stableKey(rankingsRequest) : ""; activeRankingsKey.current = rankingsKey;
  useEffect(() => {
    if (!enabled || !rankingsRequest || !resolved || resolved.error) { rankingsId.current += 1; if (resolved && !resolved.actualDate) setRankingsState({ kind: "idle" }); return; }
    if (acceptedRankingsKey.current === rankingsKey) return;
    const request = rankingsRequest; const key = rankingsKey; const requestId = ++rankingsId.current; const abort = new AbortController(); let timedOut = false;
    const timer = window.setTimeout(() => { timedOut = true; abort.abort(); }, FETCH_TIMEOUT_MS); setRankingsState({ kind: "loading" });
    fetchSectorMemberBreadthRankings(request, { signal: abort.signal }).then((payload) => {
      if (rankingsId.current !== requestId || activeRankingsKey.current !== key) return;
      const adapted = buildSectorMemberBreadthRankingsViewModel(payload, request);
      if (adapted.kind === "ready") { acceptedRankingsKey.current = key; setRankingsState({ kind: "ready", key, data: adapted.data }); }
      else if (adapted.kind === "empty") { acceptedRankingsKey.current = key; setRankingsState({ kind: "empty", key, message: adapted.message }); }
      else setRankingsState({ kind: "error", key, message: adapted.message, retryable: adapted.retryable });
    }).catch((error) => {
      if (rankingsId.current !== requestId || activeRankingsKey.current !== key || (isAbort(error, abort.signal) && !timedOut)) return;
      if (handleMismatch(error)) return;
      const next = toError(error, "成员广度榜单加载失败。"); setRankingsState({ ...next, key });
    }).finally(() => window.clearTimeout(timer));
    return () => { abort.abort(); window.clearTimeout(timer); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, rankingsKey, rankingsRetry]);

  const selectedCode = useMemo(() => {
    if (!resolved || resolved.error || !resolved.actualDate) return null;
    if (resolved.state.sectorCode && isSectorInScope(resolved.meta, resolved.state, resolved.state.sectorCode)) return resolved.state.sectorCode;
    if (rankingsState.kind !== "ready" || rankingsState.key !== rankingsKey) return null;
    return rankingsState.data.defaultSelectedSectorCode ?? rankingsState.data.rows[0]?.sectorCode ?? null;
  }, [rankingsKey, rankingsState, resolved]);

  useEffect(() => {
    if (!resolved || resolved.error || !selectedCode || resolved.state.sectorCode === selectedCode) return;
    const next = { ...resolved.state, sectorCode: selectedCode }; pendingUrlState.current = next; onNavigateSearch(buildSectorMemberBreadthSearch(next), { replace: true });
  }, [onNavigateSearch, resolved, selectedCode]);

  const detailsRequest = useMemo(() => resolved && !resolved.error && resolved.actualDate && selectedCode ? buildDetailsRequest(resolved.state, resolved.actualDate, selectedCode, resolved.meta) : null, [resolved, selectedCode]);
  const detailsKey = detailsRequest ? stableKey(detailsRequest) : ""; activeDetailsKey.current = detailsKey;
  useEffect(() => {
    if (!enabled || !detailsRequest) { detailsId.current += 1; if (!selectedCode) setDetailsState({ kind: "idle" }); return; }
    if (acceptedDetailsKey.current === detailsKey) return;
    const request = detailsRequest; const key = detailsKey; const requestId = ++detailsId.current; const abort = new AbortController(); let timedOut = false;
    const timer = window.setTimeout(() => { timedOut = true; abort.abort(); }, FETCH_TIMEOUT_MS);
    setDetailsState((current) => current.kind === "ready" ? { ...current, pending: true } : { kind: "loading" });
    fetchSectorMemberBreadthDetails(request, { signal: abort.signal }).then((payload) => {
      if (detailsId.current !== requestId || activeDetailsKey.current !== key) return;
      const adapted = buildSectorMemberBreadthDetailsViewModel(payload, request); acceptedDetailsKey.current = key;
      if (adapted.kind === "ready") { mismatchReloadAttempted.current = false; setDetailsState({ kind: "ready", data: adapted.data, pending: false }); }
      else if (adapted.kind === "empty") setDetailsState({ kind: "empty", message: adapted.message });
      else setDetailsState({ kind: "error", message: adapted.message, retryable: adapted.retryable });
    }).catch((error) => {
      if (detailsId.current !== requestId || activeDetailsKey.current !== key || (isAbort(error, abort.signal) && !timedOut)) return;
      if (handleMismatch(error)) return;
      setDetailsState(toError(error, "成员广度详情加载失败。"));
    }).finally(() => window.clearTimeout(timer));
    return () => { abort.abort(); window.clearTimeout(timer); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailsKey, detailsRetry, enabled]);

  const currentState = resolved?.state ?? urlState; if (currentState && normalizeSearch(search) === buildSectorMemberBreadthSearch(currentState)) pendingUrlState.current = currentState;
  const viewState = useMemo<SectorMemberBreadthViewState>(() => {
    if (!parsed.ok) return { kind: "error", message: parsed.message, retryable: false };
    if (!enabled || metaState.kind !== "ready") {
      if (metaState.kind === "error") return { kind: "error", message: metaState.message, retryable: metaState.retryable };
      return { kind: "loading" };
    }
    const meta = metaState.data;
    if (resolved?.error) return { kind: "error", meta, message: resolved.error, retryable: false };
    if (!resolved?.actualDate) return { kind: "empty", meta, message: "当前没有可用于成员广度分析的完整交易日。" };
    if (rankingsState.kind !== "ready") {
      if (rankingsState.kind === "empty") return { kind: "empty", meta, message: rankingsState.message };
      if (rankingsState.kind === "error") return { kind: "error", meta, message: rankingsState.message, retryable: rankingsState.retryable };
      return { kind: "loading", meta };
    }
    const delayed = currentState?.tradeDate === null && meta.dateContext.defaultStatus === "DELAYED";
    return { kind: delayed ? "delayed" : "ready", meta, rankings: rankingsState.data, details: detailsState, pending: detailsState.kind === "ready" && detailsState.pending };
  }, [currentState?.tradeDate, detailsState, enabled, metaState, parsed, rankingsState, resolved]);

  const navigate = useCallback((state: SectorMemberBreadthUrlState, options?: { replace?: boolean }) => { pendingUrlState.current = state; onNavigateSearch(buildSectorMemberBreadthSearch(state), options); }, [onNavigateSearch]);
  const update = useCallback((change: Partial<SectorMemberBreadthUrlState>, options?: { replace?: boolean }) => { const base = pendingUrlState.current ?? currentState; if (base) navigate({ ...base, ...change }, options); }, [currentState, navigate]);
  const currentRankings = rankingsState.kind === "ready" ? rankingsState.data : null;

  function invalidateAll() { metaId.current += 1; rankingsId.current += 1; detailsId.current += 1; acceptedRankingsKey.current = ""; acceptedDetailsKey.current = ""; }
  function handleMismatch(error: unknown): boolean {
    if (!(error instanceof SectorMemberBreadthApiError) || error.status !== 409 || error.code !== "SA_BREADTH_FACT_MISMATCH") return false;
    if (mismatchReloadAttempted.current) { setRankingsState({ kind: "error", key: activeRankingsKey.current, message: "行业分类版本持续变化，请稍后重试。", retryable: true }); setDetailsState({ kind: "error", message: "行业分类版本持续变化，请稍后重试。", retryable: true }); return true; }
    mismatchReloadAttempted.current = true; invalidateAll(); setMetaState({ kind: "loading" }); setRankingsState({ kind: "idle" }); setDetailsState({ kind: "idle" }); setMetaRetry((value) => value + 1); return true;
  }

  return {
    urlState: currentState, viewState,
    retry: () => { mismatchReloadAttempted.current = false; acceptedRankingsKey.current = ""; acceptedDetailsKey.current = ""; if (metaState.kind !== "ready") setMetaRetry((value) => value + 1); else if (rankingsState.kind === "error") setRankingsRetry((value) => value + 1); else setDetailsRetry((value) => value + 1); },
    retryDetails: () => { acceptedDetailsKey.current = ""; setDetailsRetry((value) => value + 1); },
    selectScope: (scope: SectorMemberBreadthUrlScope) => { const base = pendingUrlState.current ?? currentState; if (!base || metaState.kind !== "ready") return; navigate(stateForScope(base, scope, metaState.data)); },
    selectLevel1: (level1Code: string) => { const base = pendingUrlState.current ?? currentState; if (!base || metaState.kind !== "ready") return; const level2Code = base.scope === "level2-children" ? metaState.data.level2Nodes.find((node) => node.parentSectorCode === level1Code)?.sectorCode ?? null : null; navigate({ ...base, level1Code, level2Code, sectorCode: null }); },
    selectLevel2: (level2Code: string) => { const base = pendingUrlState.current ?? currentState; if (!base || metaState.kind !== "ready") return; const node = metaState.data.level2Nodes.find((item) => item.sectorCode === level2Code); if (node) navigate({ ...base, level1Code: node.rootSectorCode, level2Code, sectorCode: null }); },
    selectTradeDate: (tradeDate: string | null) => update({ tradeDate, sectorCode: null }),
    selectDirection: (direction: SectorMemberBreadthUrlDirection) => update({ direction }),
    selectMetric: (metric: SectorMemberBreadthUrlMetric) => update({ metric }),
    selectMaPeriod: (maPeriod: SectorMemberBreadthMaPeriod) => update({ maPeriod }),
    selectHistoryRange: (historyRange: SectorMemberBreadthHistoryRange) => update({ historyRange }),
    selectSector: (sectorCode: string) => update({ sectorCode }, { replace: true }),
    drillDown: (row: SectorMemberBreadthRankingRow) => { const base = pendingUrlState.current ?? currentState; if (!base || metaState.kind !== "ready") return; const node = metaState.data.hierarchy.nodes.find((item) => item.sectorCode === row.sectorCode); if (!node) return; if (row.industryLevel === 1) navigate({ ...base, scope: "level1-children", level1Code: row.sectorCode, level2Code: null, sectorCode: null }); if (row.industryLevel === 2) navigate({ ...base, scope: "level2-children", level1Code: node.rootSectorCode, level2Code: row.sectorCode, sectorCode: null }); },
    rankings: currentRankings,
  };
}

function normalizeState(state: SectorMemberBreadthUrlState, meta: SectorMemberBreadthMetaViewModel) {
  let error: string | null = null;
  if (state.tradeDate && !meta.tradeDates.some((item) => item.tradeDate === state.tradeDate)) error = "所选交易日不在可用数据范围内。";
  if (state.scope === "level1-children" && !meta.level1Nodes.some((node) => node.sectorCode === state.level1Code)) error = "所选一级行业不在当前发布分类中。";
  if (state.scope === "level2-children") { const node = meta.level2Nodes.find((item) => item.sectorCode === state.level2Code); if (!meta.level1Nodes.some((item) => item.sectorCode === state.level1Code) || !node || node.rootSectorCode !== state.level1Code) error = "所选一级、二级行业不属于同一层级路径。"; }
  if (state.sectorCode && !meta.hierarchy.nodes.some((node) => node.sectorCode === state.sectorCode)) error = "所选行业不在当前发布分类中。";
  return { state, meta, actualDate: state.tradeDate ?? meta.dateContext.defaultTradeDate, error };
}
function buildRankingsRequest(state: SectorMemberBreadthUrlState, tradeDate: string, meta: SectorMemberBreadthMetaViewModel): SectorMemberBreadthRankingsRequest { return { market: "CN_A", tradeDate, scope: toScope(state.scope), ...(state.level1Code ? { level1Code: state.level1Code } : {}), ...(state.level2Code ? { level2Code: state.level2Code } : {}), direction: toDirection(state.direction), metric: toMetric(state.metric), maPeriod: state.maPeriod, hierarchyVersion: meta.hierarchy.hierarchyVersion }; }
function buildDetailsRequest(state: SectorMemberBreadthUrlState, tradeDate: string, sectorCode: string, meta: SectorMemberBreadthMetaViewModel): SectorMemberBreadthDetailsRequest { return { market: "CN_A", tradeDate, sectorCode, direction: toDirection(state.direction), maPeriod: state.maPeriod, historyRange: state.historyRange, hierarchyVersion: meta.hierarchy.hierarchyVersion }; }
function stateForScope(state: SectorMemberBreadthUrlState, scope: SectorMemberBreadthUrlScope, meta: SectorMemberBreadthMetaViewModel): SectorMemberBreadthUrlState { const level1Code = scope === "level1-children" || scope === "level2-children" ? meta.level1Nodes[0]?.sectorCode ?? null : null; const level2Code = scope === "level2-children" ? meta.level2Nodes.find((node) => node.parentSectorCode === level1Code)?.sectorCode ?? null : null; return { ...state, scope, level1Code, level2Code, sectorCode: null }; }
function isSectorInScope(meta: SectorMemberBreadthMetaViewModel, state: SectorMemberBreadthUrlState, sectorCode: string): boolean { const node = meta.hierarchy.nodes.find((item) => item.sectorCode === sectorCode); if (!node) return false; if (state.scope === "level1") return node.industryLevel === 1; if (state.scope === "level2") return node.industryLevel === 2; if (state.scope === "level3") return node.industryLevel === 3; if (state.scope === "level1-children") return node.industryLevel === 2 && node.parentSectorCode === state.level1Code; return node.industryLevel === 3 && node.parentSectorCode === state.level2Code; }
function toScope(value: SectorMemberBreadthUrlScope): SectorMemberBreadthScope { return ({ level1: "LEVEL_1", level2: "LEVEL_2", level3: "LEVEL_3", "level1-children": "LEVEL_1_CHILDREN", "level2-children": "LEVEL_2_CHILDREN" } as const)[value]; }
function toDirection(value: SectorMemberBreadthUrlDirection): SectorMemberBreadthDirection { return value === "up" ? "UP" : "DOWN"; }
function toMetric(value: SectorMemberBreadthUrlMetric): SectorMemberBreadthMetric { return ({ "member-count": "MEMBER_COUNT", turnover: "TURNOVER", "ma-position": "MA_POSITION" } as const)[value]; }
function stableKey(value: object): string { return JSON.stringify(Object.entries(value).sort(([left], [right]) => left.localeCompare(right))); }
function normalizeSearch(search: string): string { const raw = search.replace(/^\?/, ""); return raw ? `?${raw}` : ""; }
function isAbort(error: unknown, signal: AbortSignal): boolean { return signal.aborted || (error instanceof DOMException && error.name === "AbortError"); }
function toError(error: unknown, fallback: string): { kind: "error"; message: string; retryable: boolean } { if (error instanceof DOMException && error.name === "AbortError") return { kind: "error", message: "请求超时，请稍后重试。", retryable: true }; if (error instanceof SectorMemberBreadthApiError) return { kind: "error", message: error.message || fallback, retryable: error.status >= 500 || error.status === 0 }; if (error instanceof Error) return { kind: "error", message: fallback, retryable: true }; return { kind: "error", message: fallback, retryable: true }; }

export type SectorMemberBreadthController = ReturnType<typeof useSectorMemberBreadthController>;
