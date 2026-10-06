import { useCallback, useEffect, useRef, useState } from "react";
import { DataCenterApiError, errorMessage } from "../api/dataCenterApi";
import { clientPolicy } from "../api/clientPolicy";
/** Sequential polling: a slow GET never overlaps the next GET. Unmount cancels observation only. */
export function useObserver<T>(read: ((signal: AbortSignal) => Promise<T>) | null, shouldPoll: (value: T) => boolean = () => false, seconds: number = clientPolicy.defaultPollSeconds) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const previousRead = useRef<typeof read>(null);
  const poll = useRef(shouldPoll); poll.current = shouldPoll;
  const refresh = useCallback(() => setAttempt(a => a + 1), []);
  useEffect(() => {
    if (previousRead.current !== read) setValue(null);
    previousRead.current = read; setError(null);
    if (!read) { setLoading(false); return; }
    const controller = new AbortController(); let timer: number | undefined;
    const tick = async () => {
      setLoading(true);
      try {
        const result = await read(controller.signal);
        if (controller.signal.aborted) return;
        setValue(result); setError(null);
        if (poll.current(result)) timer = window.setTimeout(tick, seconds * 1000);
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(errorMessage(e));
        if (!(e instanceof DataCenterApiError) || e.status >= 500) timer = window.setTimeout(tick, clientPolicy.readRetrySeconds * 1000);
      } finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void tick();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [read, seconds, attempt]);
  return { value, error, loading, refresh, setValue };
}
