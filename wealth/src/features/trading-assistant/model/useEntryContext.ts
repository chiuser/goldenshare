import { useEffect, useState } from "react";
import type { EntryContext } from "../api/generatedContracts";
import { getEntryContext } from "../api/tradingAssistantApi";
import { validInputField } from "../api/contractValidation";

export function useEntryContext(accountId: string, date: string, tsCode?: string) {
  const key = JSON.stringify([accountId, date, tsCode]);
  const [result, setResult] = useState<{ key: string; data: EntryContext | null; failed: boolean } | null>(null);
  const [retry, setRetry] = useState(0);
  const valid = validInputField("EntryContextQuery", "occurredOn", date);
  useEffect(() => {
    setResult(null);
    if (!valid) return;
    const controller = new AbortController();
    void getEntryContext(accountId, date, tsCode, controller.signal).then(data => {
      if (controller.signal.aborted) return;
      if (data.accountId !== accountId || data.occurredOn !== date || (data.stockRef?.tsCode ?? undefined) !== tsCode)
        throw new Error("Entry context identity mismatch");
      setResult({ key, data, failed: false });
    }).catch(() => { if (!controller.signal.aborted) setResult({ key, data: null, failed: true }); });
    return () => controller.abort();
  }, [key, valid, retry, accountId, date, tsCode]);
  const current = result?.key === key ? result : null;
  return { data: current?.data ?? null, failed: current?.failed ?? false, loading: valid && !current, retry: () => setRetry(v => v + 1) };
}
