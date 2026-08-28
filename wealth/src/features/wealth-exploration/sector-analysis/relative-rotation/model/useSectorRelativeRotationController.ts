import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { buildSectorRelativeRotationMetaViewModel, buildSectorRelativeRotationResultsViewModel } from "../api/sectorRelativeRotationAdapter";
import { fetchSectorRelativeRotationMeta, fetchSectorRelativeRotationResults, SectorRelativeRotationApiError } from "../api/sectorRelativeRotationApi";
import { buildRelativeRotationPlotScale } from "./relativeRotationPlotGeometry";
import { buildSectorRelativeRotationSearch, parseSectorRelativeRotationUrlState } from "./sectorRelativeRotationUrlState";
import type {
  RelativeRotationViewState,
  SectorHierarchyNodeResponse,
  SectorRelativeRotationMetaViewModel,
  SectorRelativeRotationPeriod,
  SectorRelativeRotationQuadrantFilter,
  SectorRelativeRotationResultsRequest,
  SectorRelativeRotationResultsViewModel,
  SectorRelativeRotationRowViewModel,
  SectorRelativeRotationTrailLength,
  SectorRelativeRotationUrlScope,
  SectorRelativeRotationUrlState,
} from "./sectorRelativeRotationTypes";

const FETCH_TIMEOUT_MS = 5000;
type NavigateSearch = (search: string, options?: { replace?: boolean }) => void;

interface UseSectorRelativeRotationControllerInput {
  enabled: boolean;
  search: string;
  onNavigateSearch: NavigateSearch;
}

type MetaState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; key: string; data: SectorRelativeRotationMetaViewModel }
  | { kind: "error"; message: string; retryable: boolean };
type ResultsState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; key: string; data: SectorRelativeRotationResultsViewModel }
  | { kind: "empty"; key: string; message: string }
  | { kind: "error"; key: string; message: string; retryable: boolean };

export function useSectorRelativeRotationController({ enabled, search, onNavigateSearch }: UseSectorRelativeRotationControllerInput) {
  const parsed = useMemo(() => parseSectorRelativeRotationUrlState(search), [search]);
  const urlState = parsed.ok ? parsed.value : null;
  const [metaState, setMetaState] = useState<MetaState>({ kind: "idle" });
  const [resultsState, setResultsState] = useState<ResultsState>({ kind: "idle" });
  const [resultsPending, setResultsPending] = useState(false);
  const [metaRetryVersion, setMetaRetryVersion] = useState(0);
  const [resultsRetryVersion, setResultsRetryVersion] = useState(0);
  const [hoveredCode, setHoveredCode] = useState<string | null>(null);
  const metaRequestId = useRef(0);
  const resultsRequestId = useRef(0);
  const activeMetaKey = useRef("");
  const activeResultsKey = useRef("");
  const acceptedResultsKey = useRef("");
  const mismatchReloadAttempted = useRef(false);
  const pendingUrlState = useRef<SectorRelativeRotationUrlState | null>(urlState);

  const metaKey = urlState ? urlState.market : "";
  activeMetaKey.current = metaKey;
  useEffect(() => {
    if (!enabled || !urlState) {
      metaRequestId.current += 1;
      resultsRequestId.current += 1;
      acceptedResultsKey.current = "";
      setMetaState({ kind: "idle" });
      setResultsState({ kind: "idle" });
      setResultsPending(false);
      return;
    }
    const key = metaKey;
    const requestId = ++metaRequestId.current;
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = window.setTimeout(() => { timedOut = true; controller.abort(); }, FETCH_TIMEOUT_MS);
    setMetaState({ kind: "loading" });
    if (mismatchReloadAttempted.current || metaState.kind !== "ready") {
      acceptedResultsKey.current = "";
      setResultsState({ kind: "idle" });
      setResultsPending(false);
    }
    fetchSectorRelativeRotationMeta(urlState.market, { signal: controller.signal })
      .then((payload) => {
        if (metaRequestId.current !== requestId || activeMetaKey.current !== key) return;
        const data = buildSectorRelativeRotationMetaViewModel(payload);
        if (metaRequestId.current !== requestId || activeMetaKey.current !== key) return;
        setMetaState({ kind: "ready", key, data });
      })
      .catch((error) => {
        if (metaRequestId.current !== requestId || activeMetaKey.current !== key || (isAbort(error, controller.signal) && !timedOut)) return;
        setMetaState(toErrorState(error, "相对轮动基础信息加载失败。"));
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  // metaState is deliberately excluded: only the request identity/retry starts Meta.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, metaKey, metaRetryVersion, urlState?.market]);

  const resolved = useMemo(() => {
    if (!urlState || metaState.kind !== "ready" || metaState.key !== metaKey) return null;
    return normalizeUrlState(urlState, metaState.data);
  }, [metaKey, metaState, urlState]);

  useEffect(() => {
    if (!resolved || resolved.error) return;
    const canonical = buildSectorRelativeRotationSearch(resolved.state);
    if (canonical !== normalizeSearch(search)) onNavigateSearch(canonical, { replace: true });
  }, [onNavigateSearch, resolved, search]);

  const resultsRequest = useMemo(() => resolved && !resolved.error ? buildResultsRequest(resolved.state, resolved.meta) : null, [resolved]);
  const resultsKey = resultsRequest ? stableRequestKey(resultsRequest) : "";
  activeResultsKey.current = resultsKey;
  useEffect(() => {
    if (!enabled || !resultsRequest || !resolved || resolved.error) {
      resultsRequestId.current += 1;
      setResultsPending(false);
      if (resolved?.error) setResultsState({ kind: "error", key: "", message: resolved.error, retryable: false });
      return;
    }
    if (acceptedResultsKey.current === resultsKey) return;
    const request = resultsRequest;
    const requestedState = resolved.state;
    const key = resultsKey;
    const requestId = ++resultsRequestId.current;
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = window.setTimeout(() => { timedOut = true; controller.abort(); }, FETCH_TIMEOUT_MS);
    setResultsPending(true);
    setResultsState((current) => current.kind === "ready" ? current : { kind: "loading" });
    fetchSectorRelativeRotationResults(request, { signal: controller.signal })
      .then((payload) => {
        if (resultsRequestId.current !== requestId || activeResultsKey.current !== key) return;
        const adapted = buildSectorRelativeRotationResultsViewModel(payload, request);
        if (resultsRequestId.current !== requestId || activeResultsKey.current !== key) return;
        if (adapted.kind === "empty") {
          acceptedResultsKey.current = key;
          setResultsState({ kind: "empty", key, message: adapted.message });
          setResultsPending(false);
          return;
        }
        if (adapted.kind === "error") {
          setResultsState({ kind: "error", key, message: adapted.message, retryable: adapted.retryable });
          setResultsPending(false);
          return;
        }
        mismatchReloadAttempted.current = false;
        const selectedState = { ...requestedState, sectorCode: adapted.data.analysis.selectedSectorCode };
        const selectedKey = stableRequestKey(buildResultsRequest(selectedState, resolved.meta));
        acceptedResultsKey.current = selectedKey;
        setResultsState({ kind: "ready", key: selectedKey, data: adapted.data });
        setResultsPending(false);
        if (requestedState.sectorCode !== selectedState.sectorCode) {
          pendingUrlState.current = selectedState;
          onNavigateSearch(buildSectorRelativeRotationSearch(selectedState), { replace: true });
        }
      })
      .catch((error) => {
        if (resultsRequestId.current !== requestId || activeResultsKey.current !== key || (isAbort(error, controller.signal) && !timedOut)) return;
        if (error instanceof SectorRelativeRotationApiError && error.status === 409 && error.code === "SA_FACT_VERSION_MISMATCH") {
          if (mismatchReloadAttempted.current) {
            setResultsState({ kind: "error", key, message: "行业分类版本持续变化，请稍后重试。", retryable: true });
            setResultsPending(false);
            return;
          }
          mismatchReloadAttempted.current = true;
          acceptedResultsKey.current = "";
          setMetaState({ kind: "loading" });
          setResultsState({ kind: "idle" });
          setResultsPending(false);
          setMetaRetryVersion((value) => value + 1);
          return;
        }
        const next = toErrorState(error, "相对轮动结果加载失败。");
        setResultsState({ ...next, key });
        setResultsPending(false);
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [enabled, onNavigateSearch, resultsKey, resultsRetryVersion]);

  const currentState = resolved?.state ?? urlState;
  if (currentState && normalizeSearch(search) === buildSectorRelativeRotationSearch(currentState)) pendingUrlState.current = currentState;
  const currentResults = resultsState.kind === "ready" ? resultsState.data : null;
  const selectedRow = currentResults?.analysis.items.find((row) => row.sectorCode === currentResults.analysis.selectedSectorCode) ?? null;
  const visibleRows = useMemo(() => {
    if (!currentResults || !currentState) return [];
    const needle = currentState.search.toLocaleLowerCase("zh-CN");
    return currentResults.analysis.items.filter((row) => {
      const matchesSearch = needle === "" || row.sectorName.toLocaleLowerCase("zh-CN").includes(needle) || row.sectorCode.toLocaleLowerCase("en-US").includes(needle);
      const matchesQuadrant = currentState.quadrant === "all" || row.rotationStatus === toRotationStatus(currentState.quadrant);
      return matchesSearch && matchesQuadrant;
    });
  }, [currentResults, currentState]);
  const plotRows = useMemo(() => currentResults?.analysis.items.filter((row) => row.coordinateStatus === "PLOTTABLE") ?? [], [currentResults]);
  const plotScale = useMemo(() => buildRelativeRotationPlotScale(plotRows, currentResults?.analysis.selectedTrail.points ?? []), [currentResults, plotRows]);

  const viewState = useMemo<RelativeRotationViewState>(() => {
    if (!parsed.ok) return { kind: "error", message: parsed.message, retryable: false };
    if (!enabled || metaState.kind === "idle" || metaState.kind === "loading") return { kind: "loading" };
    if (metaState.kind === "error") return { kind: "error", message: metaState.message, retryable: metaState.retryable };
    const meta = metaState.data;
    if (resolved?.error) return { kind: "error", meta, message: resolved.error, retryable: false };
    if (resultsState.kind === "ready") return { kind: resultsState.data.status === "DELAYED" ? "delayed" : "ready", meta, results: resultsState.data, pending: resultsPending };
    if (resultsState.kind === "idle" || resultsState.kind === "loading") return { kind: "loading", meta };
    if (resultsState.kind === "empty") return { kind: "empty", meta, message: resultsState.message };
    return { kind: "error", meta, message: resultsState.message, retryable: resultsState.retryable };
  }, [enabled, metaState, parsed, resolved, resultsPending, resultsState]);

  const navigate = useCallback((state: SectorRelativeRotationUrlState, options?: { replace?: boolean }) => {
    pendingUrlState.current = state;
    onNavigateSearch(buildSectorRelativeRotationSearch(state), options);
  }, [onNavigateSearch]);
  const updateState = useCallback((update: Partial<SectorRelativeRotationUrlState>, options?: { replace?: boolean }) => {
    const base = pendingUrlState.current ?? currentState;
    if (!base) return;
    navigate({ ...base, ...update }, options);
  }, [currentState, navigate]);

  return {
    urlState: currentState,
    viewState,
    visibleRows,
    plotRows,
    selectedRow,
    plotScale,
    hoveredCode,
    setHoveredSector: setHoveredCode,
    retry: () => {
      acceptedResultsKey.current = "";
      if (metaState.kind !== "ready") setMetaRetryVersion((value) => value + 1);
      else setResultsRetryVersion((value) => value + 1);
    },
    selectScope: (scope: SectorRelativeRotationUrlScope) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready") return;
      navigate(stateForScope(base, scope, metaState.data));
    },
    selectLevel1: (level1Code: string) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready") return;
      const level2Code = base.scope === "level2-children" ? metaState.data.level2Nodes.find((node) => node.parentSectorCode === level1Code)?.sectorCode ?? null : null;
      const parent = base.scope === "level2-children" ? level2Code : level1Code;
      navigate({ ...base, level1Code, level2Code, sectorCode: isDirectChild(metaState.data, base.sectorCode, parent) ? base.sectorCode : null });
    },
    selectLevel2: (level2Code: string) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready") return;
      const node = metaState.data.level2Nodes.find((candidate) => candidate.sectorCode === level2Code);
      if (!node) return;
      navigate({ ...base, level1Code: node.rootSectorCode, level2Code, sectorCode: isDirectChild(metaState.data, base.sectorCode, level2Code) ? base.sectorCode : null });
    },
    selectTradeDate: (tradeDate: string | null) => updateState({ tradeDate }),
    selectPeriod: (period: SectorRelativeRotationPeriod) => updateState({ period }),
    selectTrailLength: (trailLength: SectorRelativeRotationTrailLength) => updateState({ trailLength }),
    selectSector: (sectorCode: string) => updateState({ sectorCode }, { replace: true }),
    selectQuadrant: (quadrant: SectorRelativeRotationQuadrantFilter) => updateState({ quadrant }, { replace: true }),
    setSearch: (value: string) => {
      if ([...value.trim()].length > 64) return;
      updateState({ search: value.trim() }, { replace: true });
    },
    drillDown: (row: SectorRelativeRotationRowViewModel) => {
      const base = pendingUrlState.current ?? currentState;
      if (!base || metaState.kind !== "ready" || !row.canDrillDown) return;
      const node = metaState.data.hierarchy.nodes.find((candidate) => candidate.sectorCode === row.sectorCode);
      if (!node) return;
      if (row.industryLevel === 1) navigate({ ...base, scope: "level1-children", level1Code: row.sectorCode, level2Code: null, sectorCode: null });
      if (row.industryLevel === 2) navigate({ ...base, scope: "level2-children", level1Code: node.rootSectorCode, level2Code: row.sectorCode, sectorCode: null });
    },
  };
}

function normalizeUrlState(state: SectorRelativeRotationUrlState, meta: SectorRelativeRotationMetaViewModel) {
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

function buildResultsRequest(state: SectorRelativeRotationUrlState, meta: SectorRelativeRotationMetaViewModel): SectorRelativeRotationResultsRequest {
  return {
    market: state.market,
    ...(state.tradeDate ? { tradeDate: state.tradeDate } : {}),
    scope: toApiScope(state.scope),
    ...(state.scope === "level1-children" || state.scope === "level2-children" ? { level1Code: state.level1Code! } : {}),
    ...(state.scope === "level2-children" ? { level2Code: state.level2Code! } : {}),
    period: state.period,
    trailLength: state.trailLength,
    ...(state.sectorCode ? { sectorCode: state.sectorCode } : {}),
    hierarchyVersion: meta.hierarchy.hierarchyVersion,
    ...(state.debug ? { debug: 1 } : {}),
  };
}

function stateForScope(state: SectorRelativeRotationUrlState, scope: SectorRelativeRotationUrlScope, meta: SectorRelativeRotationMetaViewModel): SectorRelativeRotationUrlState {
  const selected = meta.hierarchy.nodes.find((node) => node.sectorCode === state.sectorCode);
  if (scope === "level1" || scope === "level2" || scope === "level3") {
    const expectedLevel = scope === "level1" ? 1 : scope === "level2" ? 2 : 3;
    return { ...state, scope, level1Code: null, level2Code: null, sectorCode: selected?.industryLevel === expectedLevel ? state.sectorCode : null };
  }
  if (scope === "level1-children") {
    const level1Code = selected?.industryLevel === 1 ? selected.sectorCode : selected?.rootSectorCode ?? meta.level1Nodes[0]?.sectorCode ?? null;
    return { ...state, scope, level1Code, level2Code: null, sectorCode: isDirectChild(meta, state.sectorCode, level1Code) ? state.sectorCode : null };
  }
  const level1Code = selected && selected.industryLevel > 1 ? selected.rootSectorCode : meta.level1Nodes[0]?.sectorCode ?? null;
  const level2Code = selected?.industryLevel === 2 ? selected.sectorCode : selected?.industryLevel === 3 ? selected.parentSectorCode : meta.level2Nodes.find((node) => node.parentSectorCode === level1Code)?.sectorCode ?? null;
  return { ...state, scope, level1Code, level2Code, sectorCode: isDirectChild(meta, state.sectorCode, level2Code) ? state.sectorCode : null };
}

function isDirectChild(meta: SectorRelativeRotationMetaViewModel, code: string | null, parent: string | null): boolean {
  return Boolean(code && parent && meta.hierarchy.nodes.some((node: SectorHierarchyNodeResponse) => node.sectorCode === code && node.parentSectorCode === parent));
}

function toApiScope(scope: SectorRelativeRotationUrlScope): SectorRelativeRotationResultsRequest["scope"] {
  if (scope === "level1") return "LEVEL_1";
  if (scope === "level2") return "LEVEL_2";
  if (scope === "level3") return "LEVEL_3";
  if (scope === "level1-children") return "LEVEL_1_CHILDREN";
  return "LEVEL_2_CHILDREN";
}

function toRotationStatus(quadrant: SectorRelativeRotationQuadrantFilter) {
  return quadrant.replaceAll("-", "_").toUpperCase();
}

function stableRequestKey(request: object): string {
  return Object.entries(request).filter(([, value]) => value !== undefined).sort(([left], [right]) => left.localeCompare(right)).map(([key, value]) => `${key}=${String(value)}`).join("&");
}
function normalizeSearch(search: string): string { if (!search || search === "?") return ""; return search.startsWith("?") ? search : `?${search}`; }
function isAbort(error: unknown, signal: AbortSignal) { return signal.aborted || (error instanceof DOMException && error.name === "AbortError"); }
function toErrorState(error: unknown, fallback: string) {
  const timedOut = error instanceof DOMException && error.name === "AbortError";
  const apiError = error instanceof SectorRelativeRotationApiError ? error : null;
  return { kind: "error" as const, message: timedOut ? "请求超时，请稍后重试。" : error instanceof Error ? error.message : fallback, retryable: timedOut || !apiError || apiError.status >= 500 || apiError.status === 0 };
}

export type SectorRelativeRotationController = ReturnType<typeof useSectorRelativeRotationController>;
