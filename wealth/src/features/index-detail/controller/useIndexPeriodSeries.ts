import { useCallback, useEffect, useMemo, useState } from "react";

import { DAILY_CHART_PAGE_SIZE, SSE_DAILY_PREFETCH_REMAINING } from "../../../shared/charts/dailyChartRequestLimits";
import type { DetailChartHistoryViewport } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { fetchIndexDetailKline } from "../api/indexDetailApiClient";
import type { IndexDetailKlineResponseDto, IndexLongPeriod } from "../api/indexDetailApiTypes";
import { toCandlePoint } from "../api/indexDetailViewModelAdapter";
import type { IndexCandlePoint } from "../model/indexDetailTypes";

interface PeriodRequest {
  tsCode: string;
  period: IndexLongPeriod;
  endDate: string;
}

interface PeriodSnapshot {
  phase: "loading" | "empty" | "error" | "ready" | "partial" | "delayed";
  candles: IndexCandlePoint[];
  historyPhase: "idle" | "loading" | "error";
}

interface PeriodSession {
  request: PeriodRequest;
  signal: AbortSignal | null;
  current: PeriodSnapshot;
  nextEndDate: string | null;
  viewport: DetailChartHistoryViewport | null;
  pending: { candles: IndexCandlePoint[]; thresholdDate: string; partial: boolean } | null;
  failedGesture?: symbol;
}

const INITIAL: PeriodSnapshot = { phase: "loading", candles: [], historyPhase: "idle" };

function readPeriodPage(response: IndexDetailKlineResponseDto, request: PeriodRequest) {
  const { bars, meta } = response;
  const first = bars[0]?.tradeDate;
  const last = bars.at(-1)?.tradeDate;
  if (response.indexRef.tsCode !== request.tsCode || response.period !== request.period ||
      meta.endDate !== request.endDate || meta.limit !== DAILY_CHART_PAGE_SIZE ||
      meta.count !== bars.length || bars.length > DAILY_CHART_PAGE_SIZE ||
      (last !== undefined && last > request.endDate) ||
      bars.some((bar, index) => !/^\d{4}-\d{2}-\d{2}$/.test(bar.tradeDate)
        || (index > 0 && bars[index - 1]!.tradeDate >= bar.tradeDate)) ||
      !("nextEndDate" in meta) ||
      (meta.nextEndDate !== null && (typeof meta.nextEndDate !== "string"
        || !/^\d{4}-\d{2}-\d{2}$/.test(meta.nextEndDate)
        || first === undefined || meta.nextEndDate >= first))) {
    throw new Error("指数周月线回包与请求不一致");
  }
  return { candles: bars.map(toCandlePoint), nextEndDate: meta.nextEndDate, status: response.dataStatus.status };
}

export function useIndexPeriodSeries(
  tsCode: string, period: IndexLongPeriod | null, endDate: string | null,
  loadKline: typeof fetchIndexDetailKline,
) {
  const [retryToken, setRetryToken] = useState(0);
  const session = useMemo<PeriodSession | null>(() => period && endDate ? {
    request: { tsCode, period, endDate }, signal: null, current: INITIAL,
    nextEndDate: null, viewport: null, pending: null,
  } : null, [tsCode, period, endDate, retryToken]);
  const [state, setState] = useState<{ owner: PeriodSession; snapshot: PeriodSnapshot } | null>(null);
  const publish = useCallback((owner: PeriodSession, snapshot: PeriodSnapshot) => {
    owner.current = snapshot;
    setState({ owner, snapshot });
  }, []);

  useEffect(() => {
    if (!session) {
      setState(null);
      return;
    }
    const controller = new AbortController();
    session.signal = controller.signal;
    // Strict Mode can restart the same effect before its first result arrives.
    const request = session.request;
    void loadKline({ ...request, limit: DAILY_CHART_PAGE_SIZE }, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        const page = readPeriodPage(response, request);
        session.nextEndDate = page.nextEndDate;
        const phase = page.candles.length === 0 ? "empty"
          : page.status === "DELAYED" ? "delayed" : page.status === "PARTIAL" ? "partial" : "ready";
        publish(session, { phase, candles: page.candles, historyPhase: "idle" });
      })
      .catch(() => {
        if (!controller.signal.aborted) publish(session, { ...INITIAL, phase: "error" });
      });
    return () => controller.abort();
  }, [session, loadKline, publish]);

  const showPending = useCallback((owner: PeriodSession) => {
    const { pending, viewport, current } = owner;
    if (!pending || !viewport || viewport.direction === "recent" || viewport.leftDate > pending.thresholdDate) return;
    owner.pending = null;
    publish(owner, {
      ...current, phase: pending.partial ? "partial" : current.phase,
      candles: [...pending.candles, ...current.candles],
    });
  }, [publish]);

  const onViewport = useCallback((viewport: DetailChartHistoryViewport) => {
    const owner = session;
    const signal = owner?.signal;
    const candles = owner?.current.candles;
    if (!owner || !signal || signal.aborted || !candles?.length || viewport.firstDate !== candles[0]!.time) return;
    owner.viewport = viewport.direction === "stationary" && owner.viewport
      ? { ...viewport, direction: owner.viewport.direction, gesture: owner.viewport.gesture }
      : viewport;
    if (viewport.direction !== "history") return;
    if (owner.pending) {
      showPending(owner);
      return;
    }
    if (!owner.nextEndDate || viewport.remaining > SSE_DAILY_PREFETCH_REMAINING || owner.current.historyPhase === "loading") return;
    if (owner.current.historyPhase === "error" &&
        (!viewport.beyondLeft || !viewport.gesture || viewport.gesture === owner.failedGesture)) return;

    const request = { ...owner.request, endDate: owner.nextEndDate };
    publish(owner, { ...owner.current, historyPhase: "loading" });
    void loadKline({ ...request, limit: DAILY_CHART_PAGE_SIZE }, { signal })
      .then((response) => {
        if (signal.aborted) return;
        const page = readPeriodPage(response, request);
        if (page.candles.length && page.candles.at(-1)!.time >= candles[0]!.time) {
          throw new Error("指数周月线续页日期重叠");
        }
        owner.nextEndDate = page.nextEndDate;
        if (page.candles.length) {
          owner.pending = {
            candles: page.candles,
            thresholdDate: candles[Math.min(SSE_DAILY_PREFETCH_REMAINING, candles.length) - 1]!.time,
            partial: page.status === "PARTIAL",
          };
        }
        publish(owner, { ...owner.current, historyPhase: "idle" });
        showPending(owner);
      })
      .catch(() => {
        if (signal.aborted) return;
        owner.failedGesture = owner.viewport?.gesture;
        publish(owner, { ...owner.current, historyPhase: "error" });
      });
  }, [session, loadKline, publish, showPending]);

  const retry = useCallback(() => setRetryToken(value => value + 1), []);
  return { ...(state && state.owner === session ? state.snapshot : INITIAL), onViewport, retry };
}

export type IndexPeriodSeries = ReturnType<typeof useIndexPeriodSeries>;
