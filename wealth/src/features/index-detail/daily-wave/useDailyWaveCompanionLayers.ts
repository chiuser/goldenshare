import { useCallback, useEffect, useRef, useState } from "react";

import { loadIndexNineTurnSeries } from "../api/indexNineTurnLoader";
import { fetchTrendChannel } from "../api/trendChannelApiClient";
import { buildTrendChannelViewModel } from "../api/trendChannelAdapter";
import { INDEX_DAILY_HISTORY_LIMIT } from "../model/indexDetailConstants";
import type { TrendChannelViewModel } from "../model/indexDetailTypes";
import { useNineTurnSeriesRegistry } from "../../nine-turn/controller/useNineTurnSeriesRegistry";

const DAILY = ["day"] as const;
interface Options { active: boolean; endDate: string | null; tsCode: string; supportsNineTurn: boolean; supportsTrend: boolean; }
interface TrendState { key: string; trend: TrendChannelViewModel | null; phase: "unavailable" | "loading" | "ready" | "error"; }

/** Independent instances keep research retries away from the ordinary right rail. */
export function useDailyWaveCompanionLayers({ active, endDate, tsCode, supportsNineTurn, supportsTrend }: Options) {
  const registry = useNineTurnSeriesRegistry({ endDate: active ? endDate : null, load: loadIndexNineTurnSeries,
    subjectType: "index", supportedPeriods: DAILY, supportsNineTurn: active && supportsNineTurn,
    tsCode, dailyLimit: INDEX_DAILY_HISTORY_LIMIT });
  useEffect(() => {
    if (active) void registry.ensure("day");
    else registry.clear();
  }, [active, endDate, registry.ensure, registry.clear]);

  const [retryToken, setRetryToken] = useState(0);
  const key = `${active}|${tsCode}|${endDate ?? ""}|${retryToken}`;
  const [state, setState] = useState<TrendState>({ key: "", trend: null, phase: "unavailable" });
  const sequence = useRef(0);
  useEffect(() => {
    const id = ++sequence.current;
    if (!active || !endDate || !supportsTrend || tsCode !== "000001.SH") {
      setState({ key, trend: null, phase: "unavailable" });
      return;
    }
    const controller = new AbortController();
    setState({ key, trend: null, phase: "loading" });
    fetchTrendChannel({ endDate, limit: INDEX_DAILY_HISTORY_LIMIT }, { signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted || id !== sequence.current) return;
        const trend = buildTrendChannelViewModel(payload);
        setState({ key, trend, phase: "ready" });
      })
      .catch(() => {
        if (!controller.signal.aborted && id === sequence.current) setState({ key, trend: null, phase: "error" });
      });
    return () => controller.abort();
  }, [active, endDate, key, supportsTrend, tsCode]);
  const retryTrend = useCallback(() => setRetryToken((n) => n + 1), []);
  const current = state.key === key ? state : { key, trend: null, phase: active && supportsTrend ? "loading" as const : "unavailable" as const };
  return { nineTurnLayer: registry.stateFor("day"), retryNineTurn: () => { void registry.retry("day"); },
    trend: current.trend, trendPhase: current.phase, retryTrend };
}
