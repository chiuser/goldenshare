import { useCallback, useEffect, useState } from "react";

import { buildTurnoverInsightViewModelFromApi } from "../api/turnoverInsightAdapter";
import {
  fetchTurnoverInsight,
  type TurnoverInsightRequest,
} from "../api/turnoverInsightApi";
import type { TurnoverInsightViewModel, TurnoverInsightViewState } from "./turnoverInsightTypes";

const TURNOVER_INSIGHT_TIMEOUT_MS = 5000;

interface TurnoverInsightControllerState {
  viewState: TurnoverInsightViewState;
  model: TurnoverInsightViewModel | null;
  errorMessage: string | null;
  retry: () => void;
}

function mapStatus(status: TurnoverInsightViewModel["status"]): TurnoverInsightViewState {
  return status.toLowerCase() as TurnoverInsightViewState;
}

export function useTurnoverInsightController(
  request: TurnoverInsightRequest | null,
): TurnoverInsightControllerState {
  const [attempt, setAttempt] = useState(0);
  const [viewState, setViewState] = useState<TurnoverInsightViewState>("loading");
  const [model, setModel] = useState<TurnoverInsightViewModel | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    if (request === null) {
      setViewState("loading");
      setModel(null);
      setErrorMessage(null);
      return;
    }

    let canceled = false;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), TURNOVER_INSIGHT_TIMEOUT_MS);
    setViewState("loading");
    setModel(null);
    setErrorMessage(null);

    fetchTurnoverInsight(request, { signal: controller.signal })
      .then((payload) => {
        if (canceled) return;
        const nextModel = buildTurnoverInsightViewModelFromApi(payload);
        setModel(nextModel);
        setViewState(mapStatus(nextModel.status));
        setErrorMessage(null);
      })
      .catch((error) => {
        if (canceled) return;
        const isTimeout = error instanceof DOMException && error.name === "AbortError";
        setModel(null);
        setViewState("error");
        setErrorMessage(
          isTimeout
            ? "请求超时，请稍后重试。"
            : error instanceof Error
              ? error.message
              : "成交额洞察加载失败。",
        );
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      canceled = true;
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [request?.market, request?.tradeDate, request?.debug, attempt]);

  return { viewState, model, errorMessage, retry };
}
