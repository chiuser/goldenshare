import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchMarketSectorOverview,
  MarketSectorOverviewApiError,
  type ConceptRankMetric,
  type IndustryRankMetric,
  type MarketSectorOverviewRequest,
  type MarketSectorOverviewResponse,
  type RegionRankMetric,
  type SectorOverviewDebugInfo,
  type SectorOverviewView,
} from "./api/marketSectorOverviewApi";

const FETCH_TIMEOUT_MS = 5000;

export type SectorRequestState =
  | { kind: "loading" }
  | { kind: "refreshing"; data: MarketSectorOverviewResponse }
  | { kind: "ready" | "partial" | "delayed"; data: MarketSectorOverviewResponse }
  | { kind: "empty"; data: MarketSectorOverviewResponse }
  | { kind: "forbidden" }
  | { kind: "error"; message: string };

interface TabState {
  industry: { rankMetric: IndustryRankMetric; selectedCode?: string };
  concept: { rankMetric: ConceptRankMetric; selectedCode?: string };
  region: { rankMetric: RegionRankMetric; selectedCode?: string };
}

interface ResolvedSelection {
  view: SectorOverviewView;
  rankMetric: IndustryRankMetric | ConceptRankMetric | RegionRankMetric;
  selectedCode?: string;
}

export function useSectorOverviewController({
  enabled,
  tradeDate,
  debug,
  onDebugInfo,
}: {
  enabled: boolean;
  tradeDate?: string;
  debug: boolean;
  onDebugInfo: (value: SectorOverviewDebugInfo | null) => void;
}) {
  const [view, setView] = useState<SectorOverviewView>("INDUSTRY");
  const [tabs, setTabs] = useState<TabState>({
    industry: { rankMetric: "CHANGE_PCT" },
    concept: { rankMetric: "HEAT_SCORE" },
    region: { rankMetric: "CHANGE_PCT" },
  });
  const [state, setState] = useState<SectorRequestState>({ kind: "loading" });
  const [retryVersion, setRetryVersion] = useState(0);
  const requestId = useRef(0);
  const resolvedSelection = useRef<ResolvedSelection | null>(null);

  const selectRank = useCallback((rankMetric: string) => {
    setTabs((current) => {
      if (view === "INDUSTRY") {
        return { ...current, industry: { ...current.industry, rankMetric: rankMetric as IndustryRankMetric } };
      }
      if (view === "CONCEPT") {
        return { ...current, concept: { ...current.concept, rankMetric: rankMetric as ConceptRankMetric } };
      }
      return { ...current, region: { ...current.region, rankMetric: rankMetric as RegionRankMetric } };
    });
  }, [view]);

  const selectSector = useCallback((sectorCode: string) => {
    setTabs((current) => {
      if (view === "INDUSTRY") return { ...current, industry: { ...current.industry, selectedCode: sectorCode } };
      if (view === "CONCEPT") return { ...current, concept: { ...current.concept, selectedCode: sectorCode } };
      return { ...current, region: { ...current.region, selectedCode: sectorCode } };
    });
  }, [view]);

  useEffect(() => {
    if (!enabled || !tradeDate) return;
    const tab = view === "INDUSTRY" ? tabs.industry : view === "CONCEPT" ? tabs.concept : tabs.region;
    const resolved = resolvedSelection.current;
    if (
      resolved
      && resolved.view === view
      && resolved.rankMetric === tab.rankMetric
      && resolved.selectedCode === tab.selectedCode
    ) {
      resolvedSelection.current = null;
      return;
    }
    const currentRequestId = ++requestId.current;
    const abortController = new AbortController();
    const timeoutId = window.setTimeout(() => abortController.abort(), FETCH_TIMEOUT_MS);
    setState((current) => ("data" in current ? { kind: "refreshing", data: current.data } : { kind: "loading" }));
    onDebugInfo(null);

    const params: MarketSectorOverviewRequest = {
      market: "CN_A",
      tradeDate,
      view,
      debug: debug ? 1 : 0,
    };
    if (view === "INDUSTRY") {
      params.industryRankMetric = tabs.industry.rankMetric;
      params.selectedIndustryCode = tabs.industry.selectedCode;
    } else if (view === "CONCEPT") {
      params.conceptRankMetric = tabs.concept.rankMetric;
      params.selectedConceptCode = tabs.concept.selectedCode;
    } else {
      params.regionRankMetric = tabs.region.rankMetric;
      params.selectedRegionCode = tabs.region.selectedCode;
    }

    fetchMarketSectorOverview(params, { signal: abortController.signal })
      .then((payload) => {
        if (requestId.current !== currentRequestId) return;
        const panel = payload.sectorOverview;
        if (panel.view === "INDUSTRY") {
          const selectedCode = panel.industry.selection.detailSectorCode ?? undefined;
          const selectionChanged = tabs.industry.rankMetric !== panel.industry.rankMetric
            || tabs.industry.selectedCode !== selectedCode;
          setTabs((current) => current.industry.rankMetric === panel.industry.rankMetric
              && current.industry.selectedCode === selectedCode
              ? current
              : {
                  ...current,
                  industry: {
                    rankMetric: panel.industry.rankMetric,
                    selectedCode,
                  },
                });
          resolvedSelection.current = selectionChanged
            ? { view: panel.view, rankMetric: panel.industry.rankMetric, selectedCode }
            : null;
        } else if (panel.view === "CONCEPT") {
          const selectedCode = panel.concept.selectedConceptCode ?? undefined;
          const selectionChanged = tabs.concept.rankMetric !== panel.concept.rankMetric
            || tabs.concept.selectedCode !== selectedCode;
          setTabs((current) => current.concept.rankMetric === panel.concept.rankMetric
            && current.concept.selectedCode === selectedCode
            ? current
            : {
                ...current,
                concept: {
                  rankMetric: panel.concept.rankMetric,
                  selectedCode,
                },
              });
          resolvedSelection.current = selectionChanged
            ? { view: panel.view, rankMetric: panel.concept.rankMetric, selectedCode }
            : null;
        } else {
          const selectedCode = panel.region.selectedRegionCode ?? undefined;
          const selectionChanged = tabs.region.rankMetric !== panel.region.rankMetric
            || tabs.region.selectedCode !== selectedCode;
          setTabs((current) => current.region.rankMetric === panel.region.rankMetric
            && current.region.selectedCode === selectedCode
            ? current
            : {
                ...current,
                region: {
                  rankMetric: panel.region.rankMetric,
                  selectedCode,
                },
              });
          resolvedSelection.current = selectionChanged
            ? { view: panel.view, rankMetric: panel.region.rankMetric, selectedCode }
            : null;
        }
        const status = panel.status.toLowerCase();
        setState({ kind: status === "ready" ? "ready" : status as "partial" | "delayed" | "empty", data: payload });
        onDebugInfo(debug ? payload.debugInfo ?? null : null);
      })
      .catch((error) => {
        if (requestId.current !== currentRequestId) return;
        if (error instanceof MarketSectorOverviewApiError && error.status === 403) {
          setState({ kind: "forbidden" });
        } else {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          setState({
            kind: "error",
            message: timeout
              ? "请求超时：/api/v1/wealth/market/sector-overview"
              : error instanceof Error
                ? error.message
                : "板块速览加载失败",
          });
        }
        onDebugInfo(null);
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      window.clearTimeout(timeoutId);
      abortController.abort();
    };
  }, [
    debug,
    enabled,
    onDebugInfo,
    retryVersion,
    tabs.concept.rankMetric,
    tabs.concept.selectedCode,
    tabs.industry.rankMetric,
    tabs.industry.selectedCode,
    tabs.region.rankMetric,
    tabs.region.selectedCode,
    tradeDate,
    view,
  ]);

  return {
    view,
    setView,
    state,
    selectRank,
    selectSector,
    retry: () => setRetryVersion((value) => value + 1),
  };
}
