import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  buildSectorDualMomentumMetaViewModel,
  buildSectorDualMomentumResultsViewModel,
} from "../api/sectorDualMomentumAdapter";
import {
  fetchSectorDualMomentumMeta,
  fetchSectorDualMomentumResults,
  SectorDualMomentumApiError,
} from "../api/sectorDualMomentumApi";
import {
  buildSectorDualMomentumSearch,
  parseSectorDualMomentumUrlState,
} from "./sectorDualMomentumUrlState";
import type {
  DualMomentumSortColumn,
  DualMomentumSortDirection,
  DualMomentumViewState,
  SectorDualMomentumMetaViewModel,
  SectorDualMomentumPeriod,
  SectorDualMomentumResultView,
  SectorDualMomentumResultsRequest,
  SectorDualMomentumResultsViewModel,
  SectorDualMomentumRowViewModel,
  SectorDualMomentumThreshold,
  SectorDualMomentumUrlScope,
  SectorDualMomentumUrlState,
  SectorHierarchyNodeResponse,
} from "./sectorDualMomentumTypes";

const FETCH_TIMEOUT_MS = 5000;

type NavigateSearch = (search: string, options?: { replace?: boolean }) => void;

interface UseSectorDualMomentumControllerInput {
  enabled: boolean;
  search: string;
  onNavigateSearch: NavigateSearch;
}

type MetaState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; key: string; data: SectorDualMomentumMetaViewModel }
  | { kind: "error"; message: string; retryable: boolean };

type ResultsState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; key: string; data: SectorDualMomentumResultsViewModel }
  | { kind: "empty"; key: string; message: string }
  | { kind: "error"; key: string; message: string; retryable: boolean };

export function useSectorDualMomentumController({
  enabled,
  search,
  onNavigateSearch,
}: UseSectorDualMomentumControllerInput) {
  const parsed = useMemo(() => parseSectorDualMomentumUrlState(search), [search]);
  const urlState = parsed.ok ? parsed.value : null;
  const [metaState, setMetaState] = useState<MetaState>({ kind: "idle" });
  const [resultsState, setResultsState] = useState<ResultsState>({ kind: "idle" });
  const [metaRetryVersion, setMetaRetryVersion] = useState(0);
  const [resultsRetryVersion, setResultsRetryVersion] = useState(0);
  const [sortColumn, setSortColumn] = useState<DualMomentumSortColumn>("percentile");
  const [sortDirection, setSortDirection] = useState<DualMomentumSortDirection>("desc");
  const metaRequestId = useRef(0);
  const resultsRequestId = useRef(0);
  const activeMetaKey = useRef("");
  const activeResultsKey = useRef("");
  const mismatchReloadAttempted = useRef(false);
  const pendingUrlState = useRef<SectorDualMomentumUrlState | null>(urlState);

  const metaKey = urlState ? `${urlState.market}|${urlState.debug ? 1 : 0}` : "";
  activeMetaKey.current = metaKey;

  useEffect(() => {
    if (!enabled || !urlState) {
      metaRequestId.current += 1;
      setMetaState({ kind: "idle" });
      setResultsState({ kind: "idle" });
      return;
    }
    const key = metaKey;
    const requestId = ++metaRequestId.current;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    setMetaState({ kind: "loading" });
    setResultsState({ kind: "idle" });
    fetchSectorDualMomentumMeta(urlState.market, { signal: controller.signal })
      .then((payload) => {
        if (metaRequestId.current !== requestId || activeMetaKey.current !== key) return;
        const data = buildSectorDualMomentumMetaViewModel(payload);
        if (metaRequestId.current !== requestId || activeMetaKey.current !== key) return;
        setMetaState({ kind: "ready", key, data });
      })
      .catch((error) => {
        if (metaRequestId.current !== requestId || activeMetaKey.current !== key) return;
        setMetaState(toErrorState(error, "双动量基础信息加载失败。"));
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [enabled, metaKey, metaRetryVersion, urlState?.market]);

  const resolved = useMemo(() => {
    if (!urlState || metaState.kind !== "ready" || metaState.key !== metaKey) return null;
    return normalizeUrlState(urlState, metaState.data);
  }, [metaKey, metaState, urlState]);

  useEffect(() => {
    if (!resolved || resolved.error || !urlState) return;
    const canonical = buildSectorDualMomentumSearch(resolved.state);
    if (canonical !== normalizeSearch(search)) onNavigateSearch(canonical, { replace: true });
  }, [onNavigateSearch, resolved, search, urlState]);

  const resultsRequest = useMemo(() => resolved && !resolved.error
    ? buildResultsRequest(resolved.state, resolved.meta)
    : null, [resolved]);
  const resultsKey = resultsRequest ? stableRequestKey(resultsRequest) : "";
  activeResultsKey.current = resultsKey;

  useEffect(() => {
    if (!enabled || !resultsRequest || !resolved || resolved.error) {
      resultsRequestId.current += 1;
      if (resolved?.error) setResultsState({ kind: "error", key: "", message: resolved.error, retryable: false });
      return;
    }
    const request = resultsRequest;
    const key = resultsKey;
    const requestId = ++resultsRequestId.current;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    setResultsState({ kind: "loading" });
    fetchSectorDualMomentumResults(request, { signal: controller.signal })
      .then((payload) => {
        if (resultsRequestId.current !== requestId || activeResultsKey.current !== key) return;
        const adapted = buildSectorDualMomentumResultsViewModel(payload, request);
        if (resultsRequestId.current !== requestId || activeResultsKey.current !== key) return;
        if (adapted.kind === "empty") {
          setResultsState({ kind: "empty", key, message: adapted.message });
          return;
        }
        if (adapted.kind === "error") {
          setResultsState({ kind: "error", key, message: adapted.message, retryable: adapted.retryable });
          return;
        }
        mismatchReloadAttempted.current = false;
        setResultsState({ kind: "ready", key, data: adapted.data });
      })
      .catch((error) => {
        if (resultsRequestId.current !== requestId || activeResultsKey.current !== key) return;
        if (error instanceof SectorDualMomentumApiError
          && error.status === 409
          && error.code === "SA_FACT_VERSION_MISMATCH") {
          if (mismatchReloadAttempted.current) {
            setResultsState({ kind: "error", key, message: "行业分类版本持续变化，请稍后重试。", retryable: true });
            return;
          }
          mismatchReloadAttempted.current = true;
          setMetaState({ kind: "loading" });
          setResultsState({ kind: "idle" });
          setMetaRetryVersion((value) => value + 1);
          return;
        }
        const next = toErrorState(error, "双动量结果加载失败。 ");
        setResultsState({ ...next, key });
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [enabled, resultsKey, resultsRetryVersion]);

  const currentResults = resultsState.kind === "ready" && resultsState.key === resultsKey
    ? resultsState.data
    : null;
  const selectedCode = useMemo(() => {
    if (!currentResults || !resolved) return null;
    const pool = resolved.state.resultView === "qualified"
      ? currentResults.analysis.items.filter((row) => row.qualificationStatus === "QUALIFIED")
      : currentResults.analysis.items;
    const requested = resolved.state.sectorCode;
    return requested && pool.some((row) => row.sectorCode === requested)
      ? requested
      : pool[0]?.sectorCode ?? null;
  }, [currentResults, resolved]);

  const displayRows = useMemo(() => {
    if (!currentResults || !resolved) return [];
    const rows = resolved.state.resultView === "qualified"
      ? currentResults.analysis.items.filter((row) => row.qualificationStatus === "QUALIFIED")
      : currentResults.analysis.items;
    return [...rows].sort((left, right) => localCompare(left, right, sortColumn, sortDirection));
  }, [currentResults, resolved, sortColumn, sortDirection]);
  const plotRows = currentResults?.analysis.items.filter((row) => row.coordinateStatus === "PLOTTABLE") ?? [];
  const selectedRow = currentResults?.analysis.items.find((row) => row.sectorCode === selectedCode) ?? null;

  const viewState = useMemo<DualMomentumViewState>(() => {
    if (!parsed.ok) return { kind: "error", message: parsed.message, retryable: false };
    if (!enabled || metaState.kind === "idle" || metaState.kind === "loading") return { kind: "loading" };
    if (metaState.kind === "error") return { kind: "error", message: metaState.message, retryable: metaState.retryable };
    const meta = metaState.data;
    if (resolved?.error) return { kind: "error", meta, message: resolved.error, retryable: false };
    if (resultsState.kind === "idle" || resultsState.kind === "loading") return { kind: "loading", meta };
    if (resultsState.key !== resultsKey) return { kind: "loading", meta };
    if (resultsState.kind === "empty") return { kind: "empty", meta, message: resultsState.message };
    if (resultsState.kind === "error") return { kind: "error", meta, message: resultsState.message, retryable: resultsState.retryable };
    return {
      kind: resultsState.data.status === "DELAYED" ? "delayed" : "ready",
      meta,
      results: resultsState.data,
      selectedCode,
    };
  }, [enabled, metaState, parsed, resolved, resultsKey, resultsState, selectedCode]);

  const navigate = useCallback((state: SectorDualMomentumUrlState, options?: { replace?: boolean }) => {
    pendingUrlState.current = state;
    onNavigateSearch(buildSectorDualMomentumSearch(state), options);
  }, [onNavigateSearch]);

  const currentState = resolved?.state ?? urlState;
  if (currentState && normalizeSearch(search) === buildSectorDualMomentumSearch(currentState)) {
    pendingUrlState.current = currentState;
  }

  useEffect(() => {
    if (!resolved || !currentResults || resolved.state.sectorCode === selectedCode) return;
    const base = pendingUrlState.current ?? resolved.state;
    if (stableRequestKey(buildResultsRequest(base, resolved.meta)) !== resultsKey) return;
    navigate({ ...base, sectorCode: selectedCode }, { replace: true });
  }, [currentResults, navigate, resolved, resultsKey, selectedCode]);

  const updateState = useCallback((update: Partial<SectorDualMomentumUrlState>, options?: { replace?: boolean }) => {
    const base = pendingUrlState.current ?? currentState;
    if (!base) return;
    navigate({ ...base, ...update }, options);
  }, [currentState, navigate]);

  return {
    urlState: currentState,
    viewState,
    displayRows,
    plotRows,
    selectedRow,
    sortColumn,
    sortDirection,
    retry: () => {
      mismatchReloadAttempted.current = false;
      if (metaState.kind !== "ready") setMetaRetryVersion((value) => value + 1);
      else setResultsRetryVersion((value) => value + 1);
    },
    selectScope: (scope: SectorDualMomentumUrlScope) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready") return;
      navigate(stateForScope(base, scope, metaState.data), { replace: false });
    },
    selectLevel1: (level1Code: string) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready") return;
      const level2Code = metaState.data.level2Nodes.find((node) => node.parentSectorCode === level1Code)?.sectorCode ?? null;
      const keepSelected = isDirectChild(metaState.data, base.sectorCode, base.scope === "level2-children" ? level2Code : level1Code);
      navigate({ ...base, level1Code, level2Code, sectorCode: keepSelected ? base.sectorCode : null });
    },
    selectLevel2: (level2Code: string) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready") return;
      const node = metaState.data.level2Nodes.find((candidate) => candidate.sectorCode === level2Code);
      if (!node) return;
      const keepSelected = isDirectChild(metaState.data, base.sectorCode, level2Code);
      navigate({ ...base, level1Code: node.rootSectorCode, level2Code, sectorCode: keepSelected ? base.sectorCode : null });
    },
    selectTradeDate: (tradeDate: string | null) => updateState({ tradeDate }),
    selectPeriod: (period: SectorDualMomentumPeriod) => updateState({ period }),
    selectThreshold: (threshold: SectorDualMomentumThreshold) => updateState({ threshold }),
    selectResultView: (resultView: SectorDualMomentumResultView) => updateState({ resultView }),
    selectSector: (sectorCode: string) => updateState({ sectorCode }, { replace: true }),
    drillDown: (row: SectorDualMomentumRowViewModel) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready" || !row.canDrillDown) return;
      const node = metaState.data.hierarchy.nodes.find((candidate) => candidate.sectorCode === row.sectorCode);
      if (!node) return;
      if (row.industryLevel === 1) navigate({ ...base, scope: "level1-children", level1Code: row.sectorCode, sectorCode: null });
      if (row.industryLevel === 2) navigate({ ...base, scope: "level2-children", level1Code: node.rootSectorCode, level2Code: row.sectorCode, sectorCode: null });
    },
    selectSort: (column: DualMomentumSortColumn) => {
      if (column === sortColumn) setSortDirection((direction) => direction === "desc" ? "asc" : "desc");
      else {
        setSortColumn(column);
        setSortDirection("desc");
      }
    },
  };
}

function normalizeUrlState(state: SectorDualMomentumUrlState, meta: SectorDualMomentumMetaViewModel) {
  let level1Code = meta.level1Nodes.some((node) => node.sectorCode === state.level1Code) ? state.level1Code : null;
  let level2Node = meta.level2Nodes.find((node) => node.sectorCode === state.level2Code) ?? null;
  if (level2Node && level1Code !== level2Node.rootSectorCode) level1Code = level2Node.rootSectorCode;
  if (state.scope === "level1-children" || state.scope === "level2-children") {
    level1Code ??= meta.level1Nodes[0]?.sectorCode ?? null;
  }
  if (state.scope === "level2-children") {
    if (!level2Node || level2Node.rootSectorCode !== level1Code) {
      level2Node = meta.level2Nodes.find((node) => node.parentSectorCode === level1Code) ?? null;
    }
  }
  const level2Code = level2Node?.sectorCode ?? null;
  let error: string | null = null;
  if ((state.scope === "level1-children" || state.scope === "level2-children") && !level1Code) error = "当前行业分类没有可用的一级行业。";
  if (state.scope === "level2-children" && !level2Code) error = "当前一级行业没有可用的二级行业。";
  if (state.tradeDate && !meta.tradeDates.some((item) => item.tradeDate === state.tradeDate)) error = "所选交易日不在可用数据范围内。";
  return { state: { ...state, level1Code, level2Code }, meta, error };
}

function buildResultsRequest(
  state: SectorDualMomentumUrlState,
  meta: SectorDualMomentumMetaViewModel,
): SectorDualMomentumResultsRequest {
  return {
    market: state.market,
    ...(state.tradeDate ? { tradeDate: state.tradeDate } : {}),
    scope: toApiScope(state.scope),
    ...(state.scope === "level1-children" || state.scope === "level2-children" ? { level1Code: state.level1Code! } : {}),
    ...(state.scope === "level2-children" ? { level2Code: state.level2Code! } : {}),
    period: state.period,
    leadingThreshold: state.threshold,
    hierarchyVersion: meta.hierarchy.hierarchyVersion,
    ...(state.debug ? { debug: 1 } : {}),
  };
}

function stateForScope(
  state: SectorDualMomentumUrlState,
  scope: SectorDualMomentumUrlScope,
  meta: SectorDualMomentumMetaViewModel,
): SectorDualMomentumUrlState {
  const selected = meta.hierarchy.nodes.find((node) => node.sectorCode === state.sectorCode);
  if (scope === "level1" || scope === "level2" || scope === "level3") {
    const expectedLevel = scope === "level1" ? 1 : scope === "level2" ? 2 : 3;
    return { ...state, scope, sectorCode: selected?.industryLevel === expectedLevel ? state.sectorCode : null };
  }
  if (scope === "level1-children") {
    const level1Code = selected?.industryLevel === 1 ? selected.sectorCode
      : selected?.rootSectorCode ?? state.level1Code ?? meta.level1Nodes[0]?.sectorCode ?? null;
    return { ...state, scope, level1Code, sectorCode: isDirectChild(meta, state.sectorCode, level1Code) ? state.sectorCode : null };
  }
  const level1Code = selected?.industryLevel === 2 || selected?.industryLevel === 3
    ? selected.rootSectorCode
    : state.level1Code ?? meta.level1Nodes[0]?.sectorCode ?? null;
  const level2Code = selected?.industryLevel === 2 ? selected.sectorCode
    : selected?.industryLevel === 3 ? selected.parentSectorCode
      : meta.level2Nodes.find((node) => node.parentSectorCode === level1Code)?.sectorCode ?? null;
  return { ...state, scope, level1Code, level2Code, sectorCode: isDirectChild(meta, state.sectorCode, level2Code) ? state.sectorCode : null };
}

function isDirectChild(meta: SectorDualMomentumMetaViewModel, code: string | null, parent: string | null): boolean {
  return Boolean(code && parent && meta.hierarchy.nodes.some((node) => node.sectorCode === code && node.parentSectorCode === parent));
}

function toApiScope(scope: SectorDualMomentumUrlScope) {
  if (scope === "level1") return "LEVEL_1" as const;
  if (scope === "level2") return "LEVEL_2" as const;
  if (scope === "level3") return "LEVEL_3" as const;
  if (scope === "level1-children") return "LEVEL_1_CHILDREN" as const;
  return "LEVEL_2_CHILDREN" as const;
}

function localCompare(
  left: SectorDualMomentumRowViewModel,
  right: SectorDualMomentumRowViewModel,
  column: DualMomentumSortColumn,
  direction: DualMomentumSortDirection,
) {
  const leftValue = left[column];
  const rightValue = right[column];
  if (leftValue === null && rightValue !== null) return 1;
  if (leftValue !== null && rightValue === null) return -1;
  if (leftValue === null || rightValue === null) return left.sectorCode.localeCompare(right.sectorCode);
  const order = leftValue - rightValue;
  return order === 0 ? left.sectorCode.localeCompare(right.sectorCode) : direction === "asc" ? order : -order;
}

function stableRequestKey(request: object): string {
  return Object.entries(request)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${String(value)}`)
    .join("&");
}

function normalizeSearch(search: string): string {
  if (!search || search === "?") return "";
  return search.startsWith("?") ? search : `?${search}`;
}

function toErrorState(error: unknown, fallback: string) {
  const timedOut = error instanceof DOMException && error.name === "AbortError";
  const apiError = error instanceof SectorDualMomentumApiError ? error : null;
  return {
    kind: "error" as const,
    message: timedOut ? "请求超时，请稍后重试。" : error instanceof Error ? error.message : fallback,
    retryable: timedOut || !apiError || apiError.status >= 500 || apiError.status === 0,
  };
}

export type SectorDualMomentumController = ReturnType<typeof useSectorDualMomentumController>;
