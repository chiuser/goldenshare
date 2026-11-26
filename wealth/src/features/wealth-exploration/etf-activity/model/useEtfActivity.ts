import { useEffect, useState } from "react";

import { fetchEtfActivity, type EtfActivityResponse } from "../api/etfActivityApi";

const REQUEST_TIMEOUT_MS = 5000;
const UNAVAILABLE = "ETF 动态暂不可读取，请重试";
const TIMED_OUT = "ETF 动态请求超时，请重试";

type EtfActivityState = {
  data: EtfActivityResponse | null;
  pending: boolean;
  error: string | null;
};

export function useEtfActivity() {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<EtfActivityState>({ data: null, pending: true, error: null });

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const deadline = performance.now() + REQUEST_TIMEOUT_MS;
    const timeout = () => {
      controller.abort();
      setState({ data: null, pending: false, error: TIMED_OUT });
    };
    const timer = window.setTimeout(timeout, REQUEST_TIMEOUT_MS);

    async function load() {
      if (signal.aborted) return;
      try {
        const data = await fetchEtfActivity(signal);
        if (signal.aborted) return;
        if (performance.now() >= deadline) {
          timeout();
        } else {
          setState({ data, pending: false, error: null });
        }
      } catch {
        if (!signal.aborted) {
          setState({ data: null, pending: false, error: performance.now() >= deadline ? TIMED_OUT : UNAVAILABLE });
        }
      } finally {
        window.clearTimeout(timer);
      }
    }

    // Let Strict Mode clean up its first effect before starting the request.
    queueMicrotask(() => void load());
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [attempt]);

  function retry() {
    setState((previous) => ({ ...previous, pending: true, error: null }));
    setAttempt((previous) => previous + 1);
  }

  return { ...state, retry };
}
