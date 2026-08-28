import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  buildSectorMomentumHistoryViewModel,
  buildSectorMemberDetailViewModel,
  buildSectorMomentumMetaViewModel,
  buildSectorMomentumRankingViewModel,
} from "../api/sectorMomentumAdapter";
import {
  fetchSectorMemberDetail,
  fetchSectorMomentumHistory,
  fetchSectorMomentumMeta,
  fetchSectorMomentumRankings,
  SectorMomentumApiError,
  type SectorMemberDetailRequest,
  type SectorMomentumHistoryRequest,
  type SectorMomentumRankingRequest,
} from "../api/sectorMomentumApi";
import type {
  MomentumViewState,
  MemberViewState,
  SectorHistoryRange,
  SectorHierarchyNodeResponse,
  SectorMomentumHistoryViewModel,
  SectorMomentumMetaViewModel,
  SectorMomentumPeriod,
  SectorMomentumRankingViewModel,
  SectorRankingRowViewModel,
  SectorMomentumUrlDirection,
  SectorMomentumUrlScope,
  SectorMomentumUrlState,
} from "./sectorMomentumTypes";
import {
  buildSectorMomentumSearch,
  parseSectorMomentumUrlState,
} from "./sectorMomentumUrlState";

const FETCH_TIMEOUT_MS = 5000;

type NavigateSearch = (search: string, options?: { replace?: boolean }) => void;

interface UseMomentumRankingControllerInput {
  enabled: boolean;
  search: string;
  onNavigateSearch: NavigateSearch;
}

type MetaState =
  | { kind: "loading" }
  | { kind: "ready"; data: SectorMomentumMetaViewModel }
  | { kind: "error"; message: string; retryable: boolean };

type RankingState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; key: string; data: SectorMomentumRankingViewModel }
  | { kind: "empty"; message: string; retryable: boolean }
  | { kind: "error"; message: string; retryable: boolean };

type HistoryState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; key: string; data: SectorMomentumHistoryViewModel }
  | { kind: "empty"; key: string; message: string; retryable: boolean }
  | { kind: "error"; key: string; message: string; retryable: boolean };

export function useMomentumRankingController({
  enabled,
  search,
  onNavigateSearch,
}: UseMomentumRankingControllerInput) {
  const parsed = useMemo(() => parseSectorMomentumUrlState(search), [search]);
  const [metaState, setMetaState] = useState<MetaState>({ kind: "loading" });
  const [rankingState, setRankingState] = useState<RankingState>({ kind: "idle" });
  const [historyState, setHistoryState] = useState<HistoryState>({ kind: "idle" });
  const [memberState, setMemberState] = useState<MemberViewState>({ kind: "idle" });
  const [metaRetryVersion, setMetaRetryVersion] = useState(0);
  const [rankingRetryVersion, setRankingRetryVersion] = useState(0);
  const [historyRetryVersion, setHistoryRetryVersion] = useState(0);
  const [memberRetryVersion, setMemberRetryVersion] = useState(0);
  const metaRequestId = useRef(0);
  const rankingRequestId = useRef(0);
  const historyRequestId = useRef(0);
  const memberRequestId = useRef(0);

  const urlState = parsed.ok ? parsed.value : null;

  useEffect(() => {
    if (!enabled || !urlState) return;
    const currentId = ++metaRequestId.current;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    setMetaState({ kind: "loading" });
    setRankingState({ kind: "idle" });
    setHistoryState({ kind: "idle" });
    setMemberState({ kind: "idle" });

    fetchSectorMomentumMeta(urlState.market, { signal: controller.signal })
      .then((payload) => {
        if (metaRequestId.current !== currentId) return;
        setMetaState({ kind: "ready", data: buildSectorMomentumMetaViewModel(payload) });
      })
      .catch((error) => {
        if (metaRequestId.current !== currentId) return;
        setMetaState(toErrorState(error, "板块分析基础信息加载失败。"));
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [enabled, metaRetryVersion, urlState?.market]);

  const resolved = useMemo(() => {
    if (!urlState || metaState.kind !== "ready") return null;
    return resolveRequestState(urlState, metaState.data);
  }, [metaState, urlState]);

  const rankingRequest = useMemo(() => {
    if (!resolved || !urlState) return null;
    return buildRankingRequest(resolved, urlState);
  }, [resolved, urlState]);
  const rankingKey = rankingRequest ? stableRequestKey(rankingRequest) : "";

  useEffect(() => {
    if (!enabled || !rankingRequest || !resolved) return;
    if (resolved.error) {
      setRankingState({ kind: "error", message: resolved.error, retryable: false });
      setHistoryState({ kind: "idle" });
      return;
    }
    const currentId = ++rankingRequestId.current;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    setRankingState({ kind: "loading" });

    fetchSectorMomentumRankings(rankingRequest, { signal: controller.signal })
      .then((payload) => {
        if (rankingRequestId.current !== currentId) return;
        const viewModel = buildSectorMomentumRankingViewModel(payload);
        if (viewModel.status === "EMPTY" || viewModel.status === "ERROR") {
          setRankingState({
            kind: viewModel.status === "EMPTY" ? "empty" : "error",
            message: viewModel.message,
            retryable: viewModel.status === "ERROR",
          });
          setHistoryState({ kind: "idle" });
          return;
        }
        const mismatch = findRankingRequestMismatch(viewModel, rankingRequest);
        if (mismatch) {
          setRankingState({ kind: "error", message: mismatch, retryable: true });
          setHistoryState({ kind: "idle" });
          return;
        }
        setRankingState({ kind: "ready", key: rankingKey, data: viewModel });
      })
      .catch((error) => {
        if (rankingRequestId.current !== currentId) return;
        setRankingState(toErrorState(error, "动量榜单加载失败。"));
        setHistoryState({ kind: "idle" });
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [enabled, rankingKey, rankingRetryVersion]);

  const selectedCode = useMemo(() => {
    if (rankingState.kind !== "ready" || rankingState.key !== rankingKey) return null;
    const rows = rankingState.data.rows;
    const requested = urlState?.sectorCode;
    if (requested && rows.some((row) => row.sectorCode === requested)) return requested;
    return rows.find((row) => row.returnPct !== null)?.sectorCode ?? rows[0]?.sectorCode ?? null;
  }, [rankingKey, rankingState, urlState?.sectorCode]);

  const historyRequest = useMemo(() => {
    if (!resolved || !urlState || rankingState.kind !== "ready" || rankingState.key !== rankingKey || !selectedCode) return null;
    const request = buildRankingRequest(resolved, urlState);
    const { direction: _direction, ...common } = request;
    return {
      ...common,
      historyRange: urlState.range,
      sectorCode: selectedCode,
    } satisfies SectorMomentumHistoryRequest;
  }, [rankingKey, rankingState, resolved, selectedCode, urlState]);
  const historyKey = historyRequest ? stableRequestKey(historyRequest) : "";

  const memberRequest = useMemo(() => {
    if (!urlState || rankingState.kind !== "ready" || rankingState.key !== rankingKey || !selectedCode) {
      return null;
    }
    const ranking = rankingState.data;
    if (ranking.scope !== "LEVEL_3" && ranking.scope !== "LEVEL_2_CHILDREN") return null;
    const observedTradeDate = ranking.tradingDay.observedTradeDate;
    if (!observedTradeDate) return null;
    return {
      market: urlState.market,
      tradeDate: observedTradeDate,
      hierarchyVersion: ranking.hierarchyVersion,
      sectorCode: selectedCode,
      period: ranking.period,
      direction: ranking.direction,
    } satisfies SectorMemberDetailRequest;
  }, [rankingKey, rankingState, selectedCode, urlState?.market]);
  const memberKey = memberRequest
    ? [
        memberRequest.tradeDate,
        memberRequest.hierarchyVersion,
        memberRequest.sectorCode,
        memberRequest.period,
        memberRequest.direction,
      ].join("|")
    : "";

  useEffect(() => {
    if (!enabled || !memberRequest) {
      memberRequestId.current += 1;
      setMemberState({ kind: "idle" });
      return;
    }
    if (memberState.kind === "ready" && memberState.key === memberKey) return;
    const currentId = ++memberRequestId.current;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    setMemberState({ kind: "loading", key: memberKey });

    fetchSectorMemberDetail(memberRequest, { signal: controller.signal })
      .then((payload) => {
        if (memberRequestId.current !== currentId) return;
        const viewModel = buildSectorMemberDetailViewModel(payload, memberRequest);
        if (viewModel.status === "EMPTY") {
          setMemberState({ kind: "empty", key: memberKey, message: viewModel.message });
          return;
        }
        if (viewModel.status === "ERROR") {
          setMemberState({ kind: "error", key: memberKey, message: viewModel.message, retryable: true });
          return;
        }
        setMemberState({ kind: "ready", key: memberKey, data: viewModel });
      })
      .catch((error) => {
        if (memberRequestId.current !== currentId) return;
        if (error instanceof SectorMomentumApiError
            && error.status === 409
            && error.code === "SA_MEMBER_FACT_MISMATCH") {
          setMetaState({ kind: "loading" });
          setRankingState({ kind: "idle" });
          setHistoryState({ kind: "idle" });
          setMemberState({ kind: "idle" });
          setMetaRetryVersion((value) => value + 1);
          return;
        }
        const next = toErrorState(error, "成分股数据加载失败。");
        setMemberState({ ...next, key: memberKey });
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [enabled, memberKey, memberRetryVersion]);

  useEffect(() => {
    if (!enabled || !historyRequest) return;
    if (historyState.kind === "ready" && historyState.key === historyKey) return;
    const currentId = ++historyRequestId.current;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    setHistoryState({ kind: "loading" });

    fetchSectorMomentumHistory(historyRequest, { signal: controller.signal })
      .then((payload) => {
        if (historyRequestId.current !== currentId) return;
        const viewModel = buildSectorMomentumHistoryViewModel(payload);
        if (viewModel.status === "EMPTY" || viewModel.status === "ERROR") {
          setHistoryState({
            kind: viewModel.status === "EMPTY" ? "empty" : "error",
            key: historyKey,
            message: viewModel.message,
            retryable: viewModel.status === "ERROR",
          });
          return;
        }
        const mismatch = findHistoryRequestMismatch(viewModel, historyRequest);
        if (mismatch) {
          setHistoryState({ kind: "error", key: historyKey, message: mismatch, retryable: true });
          return;
        }
        setHistoryState({ kind: "ready", key: historyKey, data: viewModel });
      })
      .catch((error) => {
        if (historyRequestId.current !== currentId) return;
        const next = toErrorState(error, "历史趋势加载失败。");
        setHistoryState({ ...next, key: historyKey });
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [enabled, historyKey, historyRetryVersion]);

  const viewState = useMemo<MomentumViewState>(() => {
    if (!parsed.ok) return { kind: "error", message: parsed.message, retryable: false };
    if (!enabled || metaState.kind === "loading") return { kind: "loading" };
    if (metaState.kind === "error") return { kind: "error", message: metaState.message, retryable: metaState.retryable };
    const meta = metaState.data;
    if (rankingState.kind === "idle" || rankingState.kind === "loading") return { kind: "loading", meta };
    if (rankingState.kind === "empty") return { kind: "empty", meta, message: rankingState.message };
    if (rankingState.kind === "error") return { kind: "error", meta, message: rankingState.message, retryable: rankingState.retryable };
    if (rankingState.key !== rankingKey) return { kind: "loading", meta };
    if (!selectedCode || historyState.kind === "idle" || historyState.kind === "loading") return { kind: "loading", meta };
    if (historyState.kind === "empty") return { kind: "empty", meta, message: historyState.message };
    if (historyState.kind === "error") return { kind: "error", meta, message: historyState.message, retryable: historyState.retryable };
    if (historyState.key !== historyKey) return { kind: "loading", meta };
    const mismatch = findFactMismatch(rankingState.data, historyState.data, selectedCode);
    if (mismatch) return { kind: "error", meta, message: mismatch, retryable: true };
    const kind = rankingState.data.status === "DELAYED" || historyState.data.status === "DELAYED"
      ? "delayed"
      : "ready";
    return {
      kind,
      meta,
      ranking: rankingState.data,
      history: historyState.data,
      selectedCode,
    };
  }, [enabled, historyKey, historyState, metaState, parsed, rankingKey, rankingState, selectedCode]);

  const navigate = useCallback((next: SectorMomentumUrlState, replace = false) => {
    onNavigateSearch(buildSectorMomentumSearch(next), { replace });
  }, [onNavigateSearch]);

  const currentState = resolved?.state ?? urlState;
  const currentSelectedCode = selectedCode ?? currentState?.sectorCode ?? null;

  return {
    urlState: currentState,
    viewState,
    memberState,
    retry: () => {
      if (metaState.kind === "error") setMetaRetryVersion((value) => value + 1);
      else if (rankingState.kind === "error") setRankingRetryVersion((value) => value + 1);
      else if (historyState.kind === "error") setHistoryRetryVersion((value) => value + 1);
    },
    retryMember: () => setMemberRetryVersion((value) => value + 1),
    selectSector: (sectorCode: string) => {
      if (!currentState) return;
      navigate({ ...currentState, sectorCode }, true);
    },
    selectScope: (scope: SectorMomentumUrlScope) => {
      if (!currentState || metaState.kind !== "ready") return;
      const next = stateForScope(currentState, scope, metaState.data, currentSelectedCode);
      navigate(next);
    },
    selectLevel1: (level1Code: string) => {
      if (!currentState || metaState.kind !== "ready") return;
      const level2Code = currentState.scope === "level2-children"
        ? firstChild(metaState.data.level2Nodes, level1Code)?.sectorCode ?? null
        : null;
      const sectorCode = isInParent(metaState.data, currentSelectedCode, level2Code ?? level1Code)
        ? currentSelectedCode
        : null;
      navigate({ ...currentState, level1Code, level2Code, sectorCode });
    },
    selectLevel2: (level2Code: string) => {
      if (!currentState || metaState.kind !== "ready") return;
      const sectorCode = isInParent(metaState.data, currentSelectedCode, level2Code) ? currentSelectedCode : null;
      navigate({ ...currentState, level2Code, sectorCode });
    },
    selectTradeDate: (tradeDate: string | null) => {
      if (currentState) navigate({ ...currentState, tradeDate, sectorCode: currentSelectedCode });
    },
    selectPeriod: (period: SectorMomentumPeriod) => {
      if (currentState) navigate({ ...currentState, period, sectorCode: currentSelectedCode });
    },
    selectDirection: (direction: SectorMomentumUrlDirection) => {
      if (currentState) navigate({ ...currentState, direction, sectorCode: currentSelectedCode });
    },
    selectRange: (range: SectorHistoryRange) => {
      if (currentState) navigate({ ...currentState, range, sectorCode: currentSelectedCode });
    },
    drillDown: (node: SectorRankingRowViewModel) => {
      if (!currentState || metaState.kind !== "ready" || !node.canDrillDown) return;
      if (node.industryLevel === 1) {
        navigate({ ...currentState, scope: "level1-children", level1Code: node.sectorCode, level2Code: null, sectorCode: null });
      } else if (node.industryLevel === 2) {
        const hierarchyNode = metaState.data.level2Nodes.find((item) => item.sectorCode === node.sectorCode);
        if (!hierarchyNode) return;
        navigate({
          ...currentState,
          scope: "level2-children",
          level1Code: hierarchyNode.rootSectorCode,
          level2Code: node.sectorCode,
          sectorCode: null,
        });
      }
    },
  };
}

function resolveRequestState(state: SectorMomentumUrlState, meta: SectorMomentumMetaViewModel) {
  let level1Code = state.level1Code;
  let level2Code = state.level2Code;
  let error: string | null = null;
  if (state.scope === "level1-children" || state.scope === "level2-children") {
    level1Code ??= meta.level1Nodes[0]?.sectorCode ?? null;
    const level1 = meta.level1Nodes.find((node) => node.sectorCode === level1Code);
    if (!level1) error = "所选一级行业不属于当前分类版本。";
  }
  if (!error && state.scope === "level2-children") {
    level2Code ??= firstChild(meta.level2Nodes, level1Code)?.sectorCode ?? null;
    const level2 = meta.level2Nodes.find(
      (node) => node.sectorCode === level2Code && node.parentSectorCode === level1Code,
    );
    if (!level2) error = "所选二级行业不属于当前一级行业。";
  }
  return { state: { ...state, level1Code, level2Code }, error };
}

function buildRankingRequest(
  resolved: ReturnType<typeof resolveRequestState>,
  source: SectorMomentumUrlState,
): SectorMomentumRankingRequest {
  const state = resolved.state;
  return {
    market: state.market,
    tradeDate: state.tradeDate ?? undefined,
    scope: toApiScope(state.scope),
    level1Code: state.scope === "level1-children" || state.scope === "level2-children"
      ? state.level1Code ?? undefined
      : undefined,
    level2Code: state.scope === "level2-children" ? state.level2Code ?? undefined : undefined,
    period: state.period,
    direction: source.direction === "gainers" ? "GAINERS" : "LOSERS",
    debug: state.debug ? 1 : undefined,
  };
}

function stateForScope(
  state: SectorMomentumUrlState,
  scope: SectorMomentumUrlScope,
  meta: SectorMomentumMetaViewModel,
  selectedCode: string | null,
): SectorMomentumUrlState {
  if (scope === "level1" || scope === "level2" || scope === "level3") {
    const level = scope === "level1" ? 1 : scope === "level2" ? 2 : 3;
    const keep = meta.hierarchy.nodes.some((node) => node.sectorCode === selectedCode && node.industryLevel === level);
    return { ...state, scope, level1Code: null, level2Code: null, sectorCode: keep ? selectedCode : null };
  }
  const selected = meta.hierarchy.nodes.find((node) => node.sectorCode === selectedCode);
  if (scope === "level1-children") {
    const level1Code = selected?.industryLevel === 1
      ? selected.sectorCode
      : selected?.industryLevel === 2
        ? selected.parentSectorCode
        : selected?.industryLevel === 3
          ? selected.rootSectorCode
          : state.level1Code ?? meta.level1Nodes[0]?.sectorCode ?? null;
    return {
      ...state,
      scope,
      level1Code,
      level2Code: null,
      sectorCode: isInParent(meta, selectedCode, level1Code) ? selectedCode : null,
    };
  }
  const level1Code = selected?.industryLevel === 2 || selected?.industryLevel === 3
    ? selected.rootSectorCode
    : state.level1Code ?? meta.level1Nodes[0]?.sectorCode ?? null;
  const level2Code = selected?.industryLevel === 2
    ? selected.sectorCode
    : selected?.industryLevel === 3
      ? selected.parentSectorCode
      : firstChild(meta.level2Nodes, level1Code)?.sectorCode ?? null;
  return {
    ...state,
    scope,
    level1Code,
    level2Code,
    sectorCode: isInParent(meta, selectedCode, level2Code) ? selectedCode : null,
  };
}

function firstChild(nodes: SectorHierarchyNodeResponse[], parentCode: string | null) {
  return nodes.find((node) => node.parentSectorCode === parentCode);
}

function isInParent(meta: SectorMomentumMetaViewModel, code: string | null, parentCode: string | null): boolean {
  return Boolean(code && parentCode && meta.hierarchy.nodes.some(
    (node) => node.sectorCode === code && node.parentSectorCode === parentCode,
  ));
}

function toApiScope(scope: SectorMomentumUrlScope) {
  if (scope === "level1") return "LEVEL_1" as const;
  if (scope === "level2") return "LEVEL_2" as const;
  if (scope === "level3") return "LEVEL_3" as const;
  if (scope === "level1-children") return "LEVEL_1_CHILDREN" as const;
  return "LEVEL_2_CHILDREN" as const;
}

function stableRequestKey(request: object): string {
  return Object.entries(request)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${String(value)}`)
    .join("&");
}

export type MomentumRankingController = ReturnType<typeof useMomentumRankingController>;

function toErrorState(error: unknown, fallback: string) {
  const timedOut = error instanceof DOMException && error.name === "AbortError";
  const apiError = error instanceof SectorMomentumApiError ? error : null;
  return {
    kind: "error" as const,
    message: timedOut ? "请求超时，请稍后重试。" : error instanceof Error ? error.message : fallback,
    retryable: timedOut || !apiError || apiError.status >= 500 || apiError.status === 0,
  };
}

function findFactMismatch(
  ranking: SectorMomentumRankingViewModel,
  history: SectorMomentumHistoryViewModel,
  selectedCode: string,
): string | null {
  if (JSON.stringify(ranking.tradingDay) !== JSON.stringify(history.tradingDay)) {
    return "榜单与历史趋势的交易日事实不一致，请重试。";
  }
  if (ranking.hierarchyVersion !== history.detail.hierarchyVersion
      || ranking.formulaVersion !== history.detail.formulaVersion
      || ranking.formulaKey !== history.detail.formulaKey) {
    return "榜单与历史趋势的分类或公式版本不一致，请重试。";
  }
  if (history.detail.sectorCode !== selectedCode) return "历史趋势返回了错误的行业。";
  return null;
}

function findRankingRequestMismatch(
  ranking: SectorMomentumRankingViewModel,
  request: SectorMomentumRankingRequest,
): string | null {
  if (ranking.scope !== request.scope || ranking.period !== request.period || ranking.direction !== request.direction) {
    return "榜单返回的比较范围、周期或方向与当前选择不一致，请重试。";
  }
  if ((ranking.parentSelection.level1Code ?? undefined) !== request.level1Code
      || (ranking.parentSelection.level2Code ?? undefined) !== request.level2Code) {
    return "榜单返回的父级范围与当前选择不一致，请重试。";
  }
  if (request.tradeDate && ranking.tradingDay.expectedTradeDate !== request.tradeDate) {
    return "榜单返回的交易日与当前选择不一致，请重试。";
  }
  return null;
}

function findHistoryRequestMismatch(
  history: SectorMomentumHistoryViewModel,
  request: SectorMomentumHistoryRequest,
): string | null {
  if (history.detail.sectorCode !== request.sectorCode) return "历史趋势返回了错误的行业。";
  if (request.tradeDate && history.tradingDay.expectedTradeDate !== request.tradeDate) {
    return "历史趋势返回的交易日与当前选择不一致，请重试。";
  }
  return null;
}
