import { useEffect, useState } from "react";

import { fetchMajorEtfMonitor, type MajorEtfMonitorResponse } from "../api/majorEtfMonitorApi";

const REQUEST_TIMEOUT_MS = 5000;

export type MajorEtfMonitorState =
  | { status: "loading" | "error" | "timeout"; data: null }
  | { status: "loaded"; data: MajorEtfMonitorResponse };

export function useMajorEtfMonitor() {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<MajorEtfMonitorState>({ status: "loading", data: null });

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const deadline = performance.now() + REQUEST_TIMEOUT_MS;
    const timeout = () => {
      controller.abort();
      setState({ status: "timeout", data: null });
    };
    const timer = window.setTimeout(timeout, REQUEST_TIMEOUT_MS);

    async function load() {
      if (signal.aborted) return;
      try {
        const data = await fetchMajorEtfMonitor(signal);
        if (signal.aborted) return;
        if (performance.now() >= deadline) {
          timeout();
        } else {
          setState({ status: "loaded", data });
        }
      } catch {
        if (signal.aborted) return;
        if (performance.now() >= deadline) {
          timeout();
        } else {
          setState({ status: "error", data: null });
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
    setState({ status: "loading", data: null });
    setAttempt((previous) => previous + 1);
  }

  return { state, retry };
}
