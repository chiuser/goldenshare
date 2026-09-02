import { useCallback, useEffect, useState } from "react";

import { buildIndexTurnoverInsightViewModelFromApi } from "../api/indexTurnoverInsightAdapter";
import {
  fetchIndexTurnoverInsight,
  IndexTurnoverInsightApiError,
  type IndexTurnoverInsightRequest,
} from "../api/indexTurnoverInsightApi";
import type {
  IndexTurnoverInsightControllerResult,
  IndexTurnoverInsightViewModel,
} from "./indexTurnoverInsightTypes";
import type { TurnoverInsightViewState } from "./turnoverInsightTypes";

const INDEX_TURNOVER_INSIGHT_TIMEOUT_MS = 5000;

function mapStatus(status: IndexTurnoverInsightViewModel["status"]): TurnoverInsightViewState {
  return status.toLowerCase() as TurnoverInsightViewState;
}

export function useIndexTurnoverInsightController(
  request: IndexTurnoverInsightRequest | null,
): IndexTurnoverInsightControllerResult {
  const [attempt, setAttempt] = useState(0);
  const [capabilityState, setCapabilityState] = useState<IndexTurnoverInsightControllerResult["capabilityState"]>("loading");
  const [viewState, setViewState] = useState<TurnoverInsightViewState>("loading");
  const [model, setModel] = useState<IndexTurnoverInsightViewModel | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    if (request === null) {
      setCapabilityState("loading");
      setViewState("loading");
      setModel(null);
      setErrorMessage(null);
      return;
    }

    let canceled = false;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), INDEX_TURNOVER_INSIGHT_TIMEOUT_MS);
    setCapabilityState("loading");
    setViewState("loading");
    setModel(null);
    setErrorMessage(null);

    const load = async () => {
      try {
        const payload = await fetchIndexTurnoverInsight(request, { signal: controller.signal });
        if (canceled) return;
        const nextModel = buildIndexTurnoverInsightViewModelFromApi(payload);
        setCapabilityState("supported");
        setModel(nextModel);
        setViewState(mapStatus(nextModel.status));
        setErrorMessage(null);
      } catch (error) {
        if (canceled) return;
        const httpStatus = error instanceof IndexTurnoverInsightApiError
          ? error.status
          : typeof error === "object" && error !== null && "status" in error
            ? (error as { status?: unknown }).status
            : null;
        if (httpStatus === 404) {
          setCapabilityState("unsupported");
          setViewState("empty");
          setModel(null);
          setErrorMessage(null);
          return;
        }
        const isTimeout = error instanceof DOMException && error.name === "AbortError";
        const message = error instanceof Error
          ? error.message
          : typeof error === "object" && error !== null && "message" in error
            ? String((error as { message?: unknown }).message ?? "")
            : "";
        setCapabilityState("supported");
        setModel(null);
        setViewState("error");
        setErrorMessage(
          isTimeout
            ? "请求超时，请稍后重试。"
            : message || "指数成交额洞察加载失败。",
        );
      } finally {
        window.clearTimeout(timeoutId);
      }
    };
    void load();

    return () => {
      canceled = true;
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [request?.market, request?.tradeDate, request?.debug, attempt]);

  return { capabilityState, viewState, model, errorMessage, retry };
}
