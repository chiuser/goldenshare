import { useCallback, useEffect, useRef, useState } from "react";
import type { IndexRecognitionDebugModule } from "./types";

type State = {
  phase: "idle" | "loading" | "ready" | "error";
  module: IndexRecognitionDebugModule | null;
  errorMessage: string;
};
const IDLE: State = { phase: "idle", module: null, errorMessage: "" };
const LOADING: State = { phase: "loading", module: null, errorMessage: "" };

export function useIndexDebugModule(enabled: boolean) {
  const [state, setState] = useState<State>(IDLE);
  const [attempt, setAttempt] = useState(0);
  const sequence = useRef(0);
  const active = useRef(enabled);
  const phase = useRef(state.phase);
  active.current = enabled;
  phase.current = state.phase;
  useEffect(() => {
    const id = ++sequence.current;
    let disposed = false;
    if (!enabled) { setState(IDLE); return; }
    setState(LOADING);
    void import("./IndexRecognitionDebug").then(module => {
      if (!disposed && active.current && id === sequence.current) {
        setState({ phase: "ready", module, errorMessage: "" });
      }
    }).catch(() => {
      if (!disposed && active.current && id === sequence.current) {
        setState({ phase: "error", module: null, errorMessage: "核验工具加载失败" });
      }
    });
    return () => { disposed = true; ++sequence.current; };
  }, [enabled, attempt]);
  const retry = useCallback(() => {
    if (active.current && phase.current === "error") {
      ++sequence.current;
      phase.current = "loading";
      setState(LOADING);
      setAttempt(previous => previous + 1);
    }
  }, []);
  return { ...(enabled ? state.phase === "idle" ? LOADING : state : IDLE), retry };
}
