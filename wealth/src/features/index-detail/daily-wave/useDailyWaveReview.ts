import { useCallback, useEffect, useRef, useState } from "react";
import { fetchIndexDetailKline, IndexDetailApiError } from "../api/indexDetailApiClient";
import { INDEX_DAILY_HISTORY_LIMIT } from "../model/indexDetailConstants";
import type { IndexPeriodKey } from "../model/indexDetailTypes";
import { DailyWaveContractError, decodeDailyWaveResponse, matchDailyWaveKline } from "./adapter";
import { fetchDailyWaveReview } from "./apiClient";
import type { DailyWaveReviewState } from "./types";

export const DAILY_WAVE_TIMEOUT_MS = 10_000;
type Snapshot = Pick<DailyWaveReviewState, "enabled" | "phase" | "response" | "candles" | "dataKey" | "errorMessage">;
const closed = (): Snapshot => ({ enabled: false, phase: "closed", response: null, candles: [], dataKey: null, errorMessage: "" });

export function useDailyWaveReview({ tsCode, activePeriod }: { tsCode: string; activePeriod: IndexPeriodKey }): DailyWaveReviewState {
  const supported = tsCode === "000001.SH" && activePeriod === "day";
  const contextKey = `${tsCode}|${activePeriod}`;
  const [snapshot, setSnapshot] = useState<Snapshot>(closed);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const owner = useRef(contextKey);

  const stop = useCallback(() => {
    sequence.current++;
    controller.current?.abort();
    controller.current = null;
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  const close = useCallback(() => { stop(); setSnapshot(closed()); }, [stop]);
  useEffect(() => {
    owner.current = contextKey;
    close();
    return stop;
  }, [contextKey, close, stop]);

  const start = useCallback(() => {
    if (!supported) return;
    stop();
    const requestId = sequence.current;
    const requestOwner = contextKey;
    const request = new AbortController();
    controller.current = request;
    const deadline = performance.now() + DAILY_WAVE_TIMEOUT_MS;
    const current = () => sequence.current === requestId && owner.current === requestOwner;
    const timeout = () => {
      if (!current()) return;
      request.abort();
      setSnapshot({ ...closed(), enabled: true, phase: "timeout", errorMessage: "波段划分计算超时，请重试" });
    };
    const check = () => {
      if (!current() || request.signal.aborted) return false;
      if (performance.now() >= deadline) { timeout(); return false; }
      return true;
    };
    timer.current = setTimeout(timeout, DAILY_WAVE_TIMEOUT_MS);
    setSnapshot({ ...closed(), enabled: true, phase: "loading" });
    void (async () => {
      try {
        const raw = await fetchDailyWaveReview({ tsCode: "000001.SH" }, { signal: request.signal });
        if (!check()) return;
        const response = decodeDailyWaveResponse(raw);
        if (!check()) return;
        if (response.status === "empty") {
          setSnapshot({ ...closed(), enabled: true, phase: "empty", response });
          return;
        }
        const kline = await fetchIndexDetailKline({ tsCode: "000001.SH", period: "day",
          startDate: response.observationStart, endDate: response.observationEnd, limit: INDEX_DAILY_HISTORY_LIMIT }, { signal: request.signal });
        if (!check()) return;
        const matched = matchDailyWaveKline(response, kline);
        if (!check()) return;
        setSnapshot(matched.matched
          ? { enabled: true, phase: "ready", response, candles: matched.candles,
            dataKey: `index:000001.SH:day:wave-review:${response.calculationId}`, errorMessage: "" }
          : { ...closed(), enabled: true, phase: "mismatch", response, errorMessage: matched.message });
      } catch (error) {
        if (!check()) return;
        setSnapshot({ ...closed(), enabled: true, phase: "error",
          errorMessage: error instanceof IndexDetailApiError || error instanceof DailyWaveContractError
            ? error.message : "波段划分计算失败，请重试" });
      } finally {
        if (current()) {
          if (timer.current !== null) clearTimeout(timer.current);
          timer.current = null;
          controller.current = null;
        }
      }
    })();
  }, [contextKey, stop, supported]);
  const visible = supported && owner.current === contextKey ? snapshot : closed();
  const toggle = useCallback(() => { if (visible.enabled) close(); else start(); }, [close, start, visible.enabled]);
  return { ...visible, supported, toggle, retry: start, close };
}
