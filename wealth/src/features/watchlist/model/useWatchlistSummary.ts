import { useEffect, useState } from "react";
import { fetchWatchlistSummary } from "../api/watchlistApi";

export function useWatchlistSummary() {
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void fetchWatchlistSummary({ signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) setCount(response.totalCount);
      })
      .catch(() => {
        if (!controller.signal.aborted) setCount(null);
      });
    return () => controller.abort();
  }, []);
  return count;
}
