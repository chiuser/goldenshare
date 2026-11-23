import { useCallback, useEffect, useMemo, useState } from "react";

import type { DetailChartHistoryViewport } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { NineTurnMarkerDto } from "../../nine-turn/api/nineTurnApiTypes";
import { fetchStockDetailKline } from "../api/stockDetailApiClient";
import type { StockDetailDataStatusDto } from "../api/stockDetailApiTypes";
import { toStockPeriodCandlePoint } from "../api/stockDetailViewModelAdapter";
import type { StockCandlePoint } from "../model/stockDetailTypes";

interface PeriodSession {
  period: "week" | "month";
  tsCode: string;
  tradeDate: string;
  debug?: 1;
  nextEndDate: string | null;
  candles: StockCandlePoint[];
  markers: NineTurnMarkerDto[];
  phase: "idle" | "loading" | "error";
  dataStatus?: StockDetailDataStatusDto;
  error?: string;
  signal?: AbortSignal;
  failedGesture?: symbol;
}

export function useStockPeriodKline(tsCode: string, period: "week" | "month" | null,
                                    tradeDate: string | undefined, debug?: 1) {
  const owner = useMemo<PeriodSession | null>(() => period && tradeDate ? {
    tsCode, period, tradeDate, debug, nextEndDate: null, candles: [], markers: [], phase: "idle",
  } : null, [tsCode, period, tradeDate, debug]);
  const [state, setState] = useState<{ owner: PeriodSession; data: PeriodSession } | null>(null);

  const load = useCallback(async (session: PeriodSession, initial: boolean, gesture?: symbol) => {
    const { signal, tsCode, period, tradeDate, debug } = session;
    const endDate = initial ? tradeDate : session.nextEndDate;
    if (!signal || signal.aborted || !endDate || session.phase === "loading") return;
    session.phase = "loading";
    session.error = undefined;
    setState({ owner: session, data: { ...session } });
    try {
      const payload = await fetchStockDetailKline({
        tsCode, period, adjustment: "forward", tradeDate, endDate, debug,
        limit: period === "week" ? 100 : undefined,
      }, { signal });
      if (signal.aborted) return;
      session.candles = [...payload.bars.map(toStockPeriodCandlePoint), ...session.candles];
      session.markers = [...(payload.nineTurnMarkers ?? []), ...session.markers];
      session.nextEndDate = payload.meta.nextEndDate ?? null;
      if (initial) session.dataStatus = payload.dataStatus;
      session.phase = "idle";
    } catch (error) {
      if (signal.aborted) return;
      session.phase = "error";
      session.error = error instanceof Error ? error.message : "周期行情加载失败";
      session.failedGesture = gesture;
    }
    setState({ owner: session, data: { ...session } });
  }, []);

  useEffect(() => {
    if (!owner) return;
    const controller = new AbortController();
    owner.signal = controller.signal;
    void load(owner, true);
    return () => {
      controller.abort();
      owner.phase = "idle";
    };
  }, [load, owner]);

  const onViewport = useCallback((viewport: DetailChartHistoryViewport) => {
    if (!owner?.dataStatus || !viewport.beyondLeft || viewport.direction !== "history"
        || viewport.firstDate !== owner.candles[0]?.fullDate) return;
    if (owner.phase === "error" && (!viewport.gesture || viewport.gesture === owner.failedGesture)) return;
    void load(owner, false, viewport.gesture);
  }, [load, owner]);
  const retry = useCallback(() => {
    if (owner) void load(owner, owner.dataStatus === undefined);
  }, [load, owner]);

  return { data: state?.owner === owner ? state.data : null, onViewport, retry };
}
