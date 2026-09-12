import { useEffect, useState } from "react";
import type { TradePreview, TradePreviewInput } from "../api/generatedContracts";
import { accountPath, request } from "../api/tradingAssistantApi";

export function useTradePreview(accountId: string, input: TradePreviewInput | null) {
  const key = input ? JSON.stringify(input) : null;
  const [result, setResult] = useState<{ key: string; data: TradePreview | null; failed: boolean } | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setResult(null);
    if (!key) return;
    const controller = new AbortController();
    void request(accountPath(accountId) + "/trades/preview", "TradePreview", { method: "POST", body: JSON.parse(key), signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setResult({ key, data, failed: false }); })
      .catch(() => { if (!controller.signal.aborted) setResult({ key, data: null, failed: true }); });
    return () => controller.abort();
  }, [accountId, key, retry]);
  const current = result?.key === key ? result : null;
  return { data: current?.data ?? null, failed: current?.failed ?? false, loading: !!key && !current, retry: () => setRetry(v => v + 1) };
}
