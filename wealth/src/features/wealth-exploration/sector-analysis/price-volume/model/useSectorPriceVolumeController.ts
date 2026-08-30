import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  buildSectorPriceVolumeDetailsViewModel,
  buildSectorPriceVolumeMetaViewModel,
  buildSectorPriceVolumeSnapshotViewModel,
} from "../api/sectorPriceVolumeAdapter";
import {
  fetchSectorPriceVolumeDetails,
  fetchSectorPriceVolumeMeta,
  fetchSectorPriceVolumeSnapshot,
  SectorPriceVolumeApiError,
} from "../api/sectorPriceVolumeApi";
import type {
  PriceVolumeDetailsRequest,
  PriceVolumeDetailsState,
  PriceVolumeHistoryRange,
  PriceVolumeMetaViewModel,
  PriceVolumePeriod,
  PriceVolumeSnapshotRequest,
  PriceVolumeSnapshotRowViewModel,
  PriceVolumeSnapshotViewModel,
  PriceVolumeSortBy,
  PriceVolumeSortDirection,
  PriceVolumeState,
  PriceVolumeStateFilter,
  PriceVolumeUrlScope,
  PriceVolumeUrlState,
  PriceVolumeViewState,
} from "../api/sectorPriceVolumeTypes";
import { buildSectorPriceVolumeSearch, parseSectorPriceVolumeUrlState } from "./sectorPriceVolumeUrlState";

const FETCH_TIMEOUT_MS = 5000;
type NavigateSearch = (search: string, options?: { replace?: boolean }) => void;

interface UseSectorPriceVolumeControllerInput {
  enabled: boolean;
  search: string;
  onNavigateSearch: NavigateSearch;
}

type MetaState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; data: PriceVolumeMetaViewModel }
  | { kind: "error"; message: string; retryable: boolean };
type SnapshotState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; key: string; data: PriceVolumeSnapshotViewModel }
  | { kind: "empty"; key: string; data: PriceVolumeSnapshotViewModel; message: string }
  | { kind: "error"; key: string; message: string; retryable: boolean };

export function useSectorPriceVolumeController({ enabled, search, onNavigateSearch }: UseSectorPriceVolumeControllerInput) {
  const parsed = useMemo(() => parseSectorPriceVolumeUrlState(search), [search]);
  const urlState = parsed.ok ? parsed.value : null;
  const urlReady = urlState !== null;
  const [metaState, setMetaState] = useState<MetaState>({ kind: "idle" });
  const [snapshotState, setSnapshotState] = useState<SnapshotState>({ kind: "idle" });
  const [detailsState, setDetailsState] = useState<PriceVolumeDetailsState>({ kind: "idle" });
  const [snapshotPending, setSnapshotPending] = useState(false);
  const [metaRetryVersion, setMetaRetryVersion] = useState(0);
  const [snapshotRetryVersion, setSnapshotRetryVersion] = useState(0);
  const [detailsRetryVersion, setDetailsRetryVersion] = useState(0);
  const [hoveredSectorCode, setHoveredSectorCode] = useState<string | null>(null);
  const metaRequestId = useRef(0);
  const snapshotRequestId = useRef(0);
  const detailsRequestId = useRef(0);
  const activeSnapshotKey = useRef("");
  const activeDetailsKey = useRef("");
  const acceptedSnapshotKey = useRef("");
  const acceptedDetailsKey = useRef("");
  const mismatchReloadAttempted = useRef(false);
  const pendingUrlState = useRef<PriceVolumeUrlState | null>(urlState);

  useEffect(() => {
    if (!enabled || !urlState) {
      metaRequestId.current += 1;
      snapshotRequestId.current += 1;
      detailsRequestId.current += 1;
      acceptedSnapshotKey.current = "";
      acceptedDetailsKey.current = "";
      setMetaState({ kind: "idle" });
      setSnapshotState({ kind: "idle" });
      setDetailsState({ kind: "idle" });
      setSnapshotPending(false);
      return;
    }
    const requestId = ++metaRequestId.current;
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = window.setTimeout(() => { timedOut = true; controller.abort(); }, FETCH_TIMEOUT_MS);
    setMetaState({ kind: "loading" });
    acceptedSnapshotKey.current = "";
    acceptedDetailsKey.current = "";
    setSnapshotState({ kind: "idle" });
    setDetailsState({ kind: "idle" });
    fetchSectorPriceVolumeMeta({ signal: controller.signal })
      .then((payload) => {
        if (metaRequestId.current !== requestId) return;
        setMetaState({ kind: "ready", data: buildSectorPriceVolumeMetaViewModel(payload) });
      })
      .catch((error) => {
        if (metaRequestId.current !== requestId || (isAbort(error, controller.signal) && !timedOut)) return;
        setMetaState(toErrorState(error, timedOut, "量价分布基础信息加载失败。"));
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => { controller.abort(); window.clearTimeout(timeoutId); };
  }, [enabled, metaRetryVersion, urlReady]);

  const resolved = useMemo(() => {
    if (!urlState || metaState.kind !== "ready") return null;
    return normalizeUrlState(urlState, metaState.data);
  }, [metaState, urlState]);

  useEffect(() => {
    if (!resolved || resolved.error) return;
    const canonical = buildSectorPriceVolumeSearch(resolved.state);
    if (canonical !== normalizeSearch(search)) onNavigateSearch(canonical, { replace: true });
  }, [onNavigateSearch, resolved, search]);

  const observedTradeDate = resolved && !resolved.error
    ? resolved.state.tradeDate ?? resolved.meta.dateContext.defaultTradeDate
    : null;
  const snapshotRequest = useMemo(() => {
    if (!resolved || resolved.error || !observedTradeDate) return null;
    return buildSnapshotRequest(resolved.state, resolved.meta, observedTradeDate);
  }, [observedTradeDate, resolved]);
  const snapshotKey = snapshotRequest ? stableRequestKey(snapshotRequest) : "";
  activeSnapshotKey.current = snapshotKey;

  useEffect(() => {
    if (!enabled || !snapshotRequest || !resolved || resolved.error) {
      snapshotRequestId.current += 1;
      setSnapshotPending(false);
      return;
    }
    if (acceptedSnapshotKey.current === snapshotKey) return;
    const request = snapshotRequest;
    const key = snapshotKey;
    const requestId = ++snapshotRequestId.current;
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = window.setTimeout(() => { timedOut = true; controller.abort(); }, FETCH_TIMEOUT_MS);
    setSnapshotPending(true);
    setSnapshotState((current) => current.kind === "ready" && !mismatchReloadAttempted.current ? current : { kind: "loading" });
    setDetailsState({ kind: "idle" });
    acceptedDetailsKey.current = "";
    fetchSectorPriceVolumeSnapshot(request, { signal: controller.signal })
      .then((payload) => {
        if (snapshotRequestId.current !== requestId || activeSnapshotKey.current !== key) return;
        const adapted = buildSectorPriceVolumeSnapshotViewModel(payload, request);
        if (snapshotRequestId.current !== requestId || activeSnapshotKey.current !== key) return;
        if (adapted.kind === "error") {
          setSnapshotState({ kind: "error", key, message: adapted.message, retryable: adapted.retryable });
        } else if (adapted.kind === "empty") {
          acceptedSnapshotKey.current = key;
          setSnapshotState({ kind: "empty", key, data: adapted.data, message: adapted.message });
        } else {
          mismatchReloadAttempted.current = false;
          acceptedSnapshotKey.current = key;
          setSnapshotState({ kind: "ready", key, data: adapted.data });
        }
        setSnapshotPending(false);
      })
      .catch((error) => {
        if (snapshotRequestId.current !== requestId || activeSnapshotKey.current !== key || (isAbort(error, controller.signal) && !timedOut)) return;
        if (handleVersionMismatch(error)) return;
        const next = toErrorState(error, timedOut, "量价分布数据读取失败。");
        setSnapshotState({ ...next, key });
        setSnapshotPending(false);
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => { controller.abort(); window.clearTimeout(timeoutId); };
  // The request object is represented by snapshotKey; retry is explicit.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, snapshotKey, snapshotRetryVersion]);

  const currentState = resolved?.state ?? urlState;
  if (currentState && normalizeSearch(search) === buildSectorPriceVolumeSearch(currentState)) pendingUrlState.current = currentState;
  const snapshot = snapshotState.kind === "ready" ? snapshotState.data : null;
  const visibleRows = useMemo(() => {
    if (!snapshot || !currentState) return [];
    const filtered = snapshot.rows.filter((row) => matchesFilter(row.state, currentState.stateFilter));
    return [...filtered].sort((left, right) => compareRows(left, right, currentState.sortBy, currentState.sortDirection));
  }, [currentState, snapshot]);
  const selectedCode = useMemo(() => {
    if (!currentState || !snapshot) return null;
    if (currentState.sectorCode && visibleRows.some((row) => row.sectorCode === currentState.sectorCode)) return currentState.sectorCode;
    return visibleRows.find((row) => row.state !== null)?.sectorCode ?? null;
  }, [currentState, snapshot, visibleRows]);
  const selectedRow = snapshot?.rows.find((row) => row.sectorCode === selectedCode) ?? null;

  useEffect(() => {
    if (!currentState || !snapshot || currentState.sectorCode === selectedCode) return;
    const next = { ...currentState, sectorCode: selectedCode };
    pendingUrlState.current = next;
    onNavigateSearch(buildSectorPriceVolumeSearch(next), { replace: true });
  }, [currentState, onNavigateSearch, selectedCode, snapshot]);

  const detailsRequest = useMemo(() => {
    if (!snapshotRequest || !currentState || !selectedCode || snapshotState.kind !== "ready") return null;
    return { ...snapshotRequest, historyRange: currentState.historyRange, sectorCode: selectedCode } satisfies PriceVolumeDetailsRequest;
  }, [currentState, selectedCode, snapshotRequest, snapshotState.kind]);
  const detailsKey = detailsRequest ? stableRequestKey(detailsRequest) : "";
  activeDetailsKey.current = detailsKey;

  useEffect(() => {
    if (!enabled || !detailsRequest) {
      detailsRequestId.current += 1;
      setDetailsState({ kind: "idle" });
      return;
    }
    if (acceptedDetailsKey.current === detailsKey) return;
    const request = detailsRequest;
    const key = detailsKey;
    const requestId = ++detailsRequestId.current;
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = window.setTimeout(() => { timedOut = true; controller.abort(); }, FETCH_TIMEOUT_MS);
    setDetailsState({ kind: "loading" });
    fetchSectorPriceVolumeDetails(request, { signal: controller.signal })
      .then((payload) => {
        if (detailsRequestId.current !== requestId || activeDetailsKey.current !== key) return;
        const adapted = buildSectorPriceVolumeDetailsViewModel(payload, request);
        if (detailsRequestId.current !== requestId || activeDetailsKey.current !== key) return;
        if (adapted.kind === "error") setDetailsState({ kind: "error", message: adapted.message, retryable: adapted.retryable });
        else if (adapted.kind === "empty") { acceptedDetailsKey.current = key; setDetailsState({ kind: "empty", data: adapted.data, message: adapted.message }); }
        else { acceptedDetailsKey.current = key; setDetailsState({ kind: "ready", data: adapted.data }); }
      })
      .catch((error) => {
        if (detailsRequestId.current !== requestId || activeDetailsKey.current !== key || (isAbort(error, controller.signal) && !timedOut)) return;
        if (handleVersionMismatch(error)) return;
        setDetailsState(toErrorState(error, timedOut, "历史变化读取失败。"));
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => { controller.abort(); window.clearTimeout(timeoutId); };
  // The complete request identity is detailsKey; retry is explicit.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailsKey, detailsRetryVersion, enabled]);

  const viewState = useMemo<PriceVolumeViewState>(() => {
    if (!parsed.ok) return { kind: "error", message: parsed.message, retryable: false };
    if (!enabled || metaState.kind === "idle" || metaState.kind === "loading") return { kind: "loading" };
    if (metaState.kind === "error") return { kind: "error", message: metaState.message, retryable: metaState.retryable };
    const meta = metaState.data;
    if (resolved?.error) return { kind: "error", meta, message: resolved.error, retryable: false };
    if (!observedTradeDate) return { kind: "empty", meta, message: "当前尚无完整量价交易日。" };
    if (snapshotState.kind === "ready") {
      const delayed = currentState?.tradeDate === null && meta.dateContext.defaultStatus === "DELAYED";
      return { kind: delayed ? "delayed" : "ready", meta, snapshot: snapshotState.data, pending: snapshotPending };
    }
    if (snapshotState.kind === "empty") return { kind: "empty", meta, snapshot: snapshotState.data, message: snapshotState.message };
    if (snapshotState.kind === "error") return { kind: "error", meta, message: snapshotState.message, retryable: snapshotState.retryable };
    return { kind: "loading", meta };
  }, [currentState?.tradeDate, enabled, metaState, observedTradeDate, parsed, resolved, snapshotPending, snapshotState]);

  const navigate = useCallback((state: PriceVolumeUrlState, options?: { replace?: boolean }) => {
    pendingUrlState.current = state;
    onNavigateSearch(buildSectorPriceVolumeSearch(state), options);
  }, [onNavigateSearch]);
  const updateState = useCallback((update: Partial<PriceVolumeUrlState>, options?: { replace?: boolean }) => {
    const base = pendingUrlState.current ?? currentState;
    if (!base) return;
    navigate({ ...base, ...update }, options);
  }, [currentState, navigate]);

  function handleVersionMismatch(error: unknown) {
    if (!(error instanceof SectorPriceVolumeApiError) || error.status !== 409 || error.code !== "SA_PRICE_VOLUME_FACT_MISMATCH") return false;
    if (mismatchReloadAttempted.current) {
      setSnapshotState({ kind: "error", key: activeSnapshotKey.current, message: "行业分类版本持续变化，请稍后重试。", retryable: true });
      setDetailsState({ kind: "idle" });
      setSnapshotPending(false);
      return true;
    }
    mismatchReloadAttempted.current = true;
    acceptedSnapshotKey.current = "";
    acceptedDetailsKey.current = "";
    setMetaState({ kind: "loading" });
    setSnapshotState({ kind: "idle" });
    setDetailsState({ kind: "idle" });
    setSnapshotPending(false);
    setMetaRetryVersion((value) => value + 1);
    return true;
  }

  return {
    urlState: currentState,
    viewState,
    detailsState,
    visibleRows,
    plotRows: snapshot?.rows.filter((row) => row.state !== null) ?? [],
    selectedRow,
    hoveredSectorCode,
    setHoveredSector: setHoveredSectorCode,
    retry: () => {
      acceptedSnapshotKey.current = "";
      if (metaState.kind !== "ready") setMetaRetryVersion((value) => value + 1);
      else setSnapshotRetryVersion((value) => value + 1);
    },
    retryDetails: () => { acceptedDetailsKey.current = ""; setDetailsRetryVersion((value) => value + 1); },
    selectScope: (scope: PriceVolumeUrlScope) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready") return;
      navigate(stateForScope(base, scope, metaState.data));
    },
    selectLevel1: (level1Code: string) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready") return;
      const level2Code = base.scope === "level2-children" ? metaState.data.level2Nodes.find((node) => node.parentSectorCode === level1Code)?.sectorCode ?? null : null;
      navigate({ ...base, level1Code, level2Code, sectorCode: null });
    },
    selectLevel2: (level2Code: string) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready") return;
      const node = metaState.data.level2Nodes.find((candidate) => candidate.sectorCode === level2Code);
      if (node) navigate({ ...base, level1Code: node.rootSectorCode, level2Code, sectorCode: null });
    },
    selectTradeDate: (tradeDate: string | null) => updateState({ tradeDate, sectorCode: null }),
    selectPeriod: (period: PriceVolumePeriod) => updateState({ period, sectorCode: null }),
    selectStateFilter: (stateFilter: PriceVolumeStateFilter) => updateState({ stateFilter }, { replace: true }),
    selectSortBy: (sortBy: PriceVolumeSortBy) => updateState({ sortBy }, { replace: true }),
    selectSortDirection: (sortDirection: PriceVolumeSortDirection) => updateState({ sortDirection }, { replace: true }),
    selectSector: (sectorCode: string) => updateState({ sectorCode }, { replace: true }),
    selectHistoryRange: (historyRange: PriceVolumeHistoryRange) => updateState({ historyRange }, { replace: true }),
    drillDown: (row: PriceVolumeSnapshotRowViewModel) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || !row.canDrillDown) return;
      if (row.industryLevel === 1) navigate({ ...base, scope: "level1-children", level1Code: row.sectorCode, level2Code: null, sectorCode: null });
      if (row.industryLevel === 2) navigate({ ...base, scope: "level2-children", level1Code: row.rootSectorCode, level2Code: row.sectorCode, sectorCode: null });
    },
  };
}

function normalizeUrlState(state: PriceVolumeUrlState, meta: PriceVolumeMetaViewModel) {
  let error: string | null = null;
  if (state.tradeDate && !meta.tradeDates.some((item) => item.tradeDate === state.tradeDate)) error = "所选交易日不在可用数据范围内。";
  if (state.scope === "level1-children" && !meta.level1Nodes.some((node) => node.sectorCode === state.level1Code)) error = "所选一级行业不在当前发布分类中。";
  if (state.scope === "level2-children") {
    const level2 = meta.level2Nodes.find((node) => node.sectorCode === state.level2Code);
    if (!meta.level1Nodes.some((node) => node.sectorCode === state.level1Code) || !level2 || level2.rootSectorCode !== state.level1Code) error = "所选一级、二级行业不属于同一层级路径。";
  }
  if (state.sectorCode && !meta.hierarchy.nodes.some((node) => node.sectorCode === state.sectorCode)) error = "所选行业不在当前发布分类中。";
  return { state, meta, error };
}

function buildSnapshotRequest(state: PriceVolumeUrlState, meta: PriceVolumeMetaViewModel, tradeDate: string): PriceVolumeSnapshotRequest {
  return {
    market: "CN_A", tradeDate, scope: toApiScope(state.scope),
    ...(state.scope === "level1-children" || state.scope === "level2-children" ? { level1Code: state.level1Code! } : {}),
    ...(state.scope === "level2-children" ? { level2Code: state.level2Code! } : {}),
    period: state.period, hierarchyVersion: meta.hierarchy.hierarchyVersion,
  };
}

function stateForScope(state: PriceVolumeUrlState, scope: PriceVolumeUrlScope, meta: PriceVolumeMetaViewModel): PriceVolumeUrlState {
  if (["level1", "level2", "level3"].includes(scope)) return { ...state, scope, level1Code: null, level2Code: null, sectorCode: null };
  if (scope === "level1-children") return { ...state, scope, level1Code: meta.level1Nodes[0]?.sectorCode ?? null, level2Code: null, sectorCode: null };
  const level1Code = meta.level1Nodes[0]?.sectorCode ?? null;
  const level2Code = meta.level2Nodes.find((node) => node.parentSectorCode === level1Code)?.sectorCode ?? null;
  return { ...state, scope, level1Code, level2Code, sectorCode: null };
}

function toApiScope(scope: PriceVolumeUrlScope): PriceVolumeSnapshotRequest["scope"] { if (scope === "level1") return "LEVEL_1"; if (scope === "level2") return "LEVEL_2"; if (scope === "level3") return "LEVEL_3"; if (scope === "level1-children") return "LEVEL_1_CHILDREN"; return "LEVEL_2_CHILDREN"; }
function matchesFilter(state: PriceVolumeState | null, filter: PriceVolumeStateFilter) { if (filter === "all") return true; if (filter === "joint") return state === "JOINT"; if (filter === "price") return state === "PRICE_ONLY"; if (filter === "amount") return state === "AMOUNT_ONLY"; return state === "NEUTRAL"; }
function compareRows(left: PriceVolumeSnapshotRowViewModel, right: PriceVolumeSnapshotRowViewModel, sortBy: PriceVolumeSortBy, direction: PriceVolumeSortDirection) { const leftValue = sortBy === "price-momentum" ? left.priceMomentumPct : left.amountActivityPct; const rightValue = sortBy === "price-momentum" ? right.priceMomentumPct : right.amountActivityPct; if (leftValue === null && rightValue !== null) return 1; if (leftValue !== null && rightValue === null) return -1; if (leftValue !== null && rightValue !== null && leftValue !== rightValue) return direction === "desc" ? rightValue - leftValue : leftValue - rightValue; return left.sectorCode.localeCompare(right.sectorCode); }
function stableRequestKey(request: object) { return Object.entries(request).filter(([, value]) => value !== undefined).sort(([left], [right]) => left.localeCompare(right)).map(([key, value]) => `${key}=${String(value)}`).join("&"); }
function normalizeSearch(search: string) { if (!search || search === "?") return ""; return search.startsWith("?") ? search : `?${search}`; }
function isAbort(error: unknown, signal: AbortSignal) { return signal.aborted || (error instanceof DOMException && error.name === "AbortError"); }
function toErrorState(error: unknown, timedOut: boolean, fallback: string) { const apiError = error instanceof SectorPriceVolumeApiError ? error : null; return { kind: "error" as const, message: timedOut ? "请求超时，请稍后重试。" : error instanceof Error ? error.message : fallback, retryable: timedOut || !apiError || apiError.status >= 500 || apiError.status === 0 }; }

export type SectorPriceVolumeController = ReturnType<typeof useSectorPriceVolumeController>;
