import { useCallback, useEffect, useRef, useState } from "react";
import { checkRequest } from "../xxm/apiClient";
import { XXM_SPEC_HASH } from "../xxm/types";
import type { DecodeForecastDebug } from "../debug/types";
import { XXM_FORECAST_VERSION, XXM_FORECAST_SPEC_HASH } from "./types";
import { fetchForecast } from "./apiClient";
import { FORECAST_PERIODS, type ForecastPeriod, type ForecastRows } from "./types";

// Clients use the page-wide scheduler; this hook owns row identity and refresh.
function initial(minutes: boolean): ForecastRows {
  return Object.fromEntries(FORECAST_PERIODS.map(p => [p, { phase: p !== "day" && !minutes ? "unsupported" : "idle", response: null, error: "" }])) as ForecastRows;
}
export function useXxmForecast({ active, tsCode, historicalDate, minutes, enabled, debug, decodeDebug }: {
  active: boolean; tsCode: string; historicalDate?: string; minutes: boolean; enabled: boolean; debug: 0|1; decodeDebug?: DecodeForecastDebug;
}) {
  const [rows, setRows] = useState(() => initial(minutes));
  const retryRef = useRef<(p: ForecastPeriod) => void>(() => {});
  const identity = `${XXM_FORECAST_VERSION}|${XXM_FORECAST_SPEC_HASH}|${XXM_SPEC_HASH}|${enabled}|${debug}|${tsCode}|${historicalDate ?? "latest"}|${minutes}`;
  const [stateIdentity, setStateIdentity] = useState(identity);
  useEffect(() => {
    let disposed = false, generation = 0, running = 0;
    let timer: number | undefined;
    let refreshMs: number | undefined;
    let queue: ForecastPeriod[] = [];
    const controllers = new Map<ForecastPeriod, AbortController>();
    const supported = enabled && import.meta.env.DEV && tsCode === "000001.SH" && (debug === 0 || !!decodeDebug);
    setStateIdentity(identity);
    setRows(initial(minutes));
    retryRef.current = () => {};
    if (!supported) return;
    const visible = () => active && supported && document.visibilityState !== "hidden" && !disposed;
    const asOf = (p: ForecastPeriod) => historicalDate ? p === "day" ? historicalDate : `${historicalDate}T15:00:00+08:00` : undefined;
    const stop = () => {
      generation++;
      if (timer !== undefined) window.clearTimeout(timer);
      timer = undefined;
      queue = [];
      controllers.forEach(c => c.abort());
      controllers.clear();
      running = 0;
    };
    const schedule = () => {
      if (visible() && !historicalDate && refreshMs && !queue.length && !running) {
        if (timer !== undefined) window.clearTimeout(timer);
        timer = window.setTimeout(() => enqueue(FORECAST_PERIODS.filter(p => p === "day" || minutes)), refreshMs);
      }
    };
    const pump = () => {
      while (visible() && queue.length) {
        const p = queue.shift()!;
        const controller = new AbortController();
        const current = generation;
        controllers.set(p, controller);
        running++;
        setRows(r => ({ ...r, [p]: r[p].response ? r[p] : { phase: "loading", response: null, error: "" } }));
        fetchForecast(p, asOf(p), controller.signal, { debug: debug === 1 ? 1 : undefined, decodeDebug }).then(({response, deadline}) => {
          if (disposed || current !== generation || controller.signal.aborted) return;
          checkRequest(controller.signal, deadline);
          refreshMs = response.refreshAfterMs;
          checkRequest(controller.signal, deadline);
          setRows(r => ({ ...r, [p]: { phase: "ready", response, error: "" } }));
        }).catch((error: unknown) => {
          if (disposed || current !== generation || controller.signal.aborted) return;
          setRows(r => ({ ...r, [p]: { phase: "error", response: null,
            error: error instanceof Error ? error.message : "关键点预判加载失败，请重试" } }));
        }).finally(() => {
          if (disposed || current !== generation) return;
          controllers.delete(p);
          running--;
          pump();
          schedule();
        });
      }
    };
    const enqueue = (periods: readonly ForecastPeriod[]) => {
      if (!visible()) return;
      for (const p of periods) if ((p === "day" || minutes) && !queue.includes(p) && !controllers.has(p)) queue.push(p);
      pump();
    };
    retryRef.current = p => enqueue([p]);
    const resume = () => {
      if (!visible()) { stop(); return; }
      enqueue(FORECAST_PERIODS.filter(p => p === "day" || minutes));
    };
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("focus", resume);
    resume();
    return () => {
      disposed = true;
      retryRef.current = () => {};
      stop();
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("focus", resume);
    };
  }, [active, tsCode, historicalDate, minutes, identity, enabled, debug, decodeDebug]);
  const retry = useCallback((p: ForecastPeriod) => retryRef.current(p), []);
  return { rows: stateIdentity === identity ? rows : initial(minutes), retry };
}
