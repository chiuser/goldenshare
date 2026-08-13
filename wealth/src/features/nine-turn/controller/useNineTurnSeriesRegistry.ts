import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import { NineTurnApiError } from "../api/nineTurnApiClient";
import type {
  NineTurnPeriod,
  NineTurnSeriesDto,
  NineTurnSubjectType,
} from "../api/nineTurnApiTypes";
import {
  adaptNineTurnSeries,
  idleNineTurnLayer,
  unsupportedNineTurnLayer,
} from "../model/nineTurnAdapter";
import type { NineTurnLayerViewModel } from "../model/nineTurnTypes";

export interface NineTurnSeriesLoadRequest {
  endDate: string;
  limit: number;
  period: NineTurnPeriod;
  subjectType: NineTurnSubjectType;
  tsCode: string;
}

export type NineTurnSeriesLoader = (
  request: NineTurnSeriesLoadRequest,
  options: { signal?: AbortSignal },
) => Promise<NineTurnSeriesDto>;

interface RegistryEntry {
  controller: AbortController | null;
  requestId: number;
  view: NineTurnLayerViewModel;
}

interface UseNineTurnSeriesRegistryOptions {
  endDate: string | null;
  load: NineTurnSeriesLoader;
  subjectType: NineTurnSubjectType;
  supportedPeriods: readonly NineTurnPeriod[];
  supportsNineTurn: boolean;
  tsCode: string;
}

export function useNineTurnSeriesRegistry({
  endDate,
  load,
  subjectType,
  supportedPeriods,
  supportsNineTurn,
  tsCode,
}: UseNineTurnSeriesRegistryOptions) {
  const entriesRef = useRef(new Map<string, RegistryEntry>());
  const requestSequenceRef = useRef(0);
  const [, refresh] = useReducer((value: number) => value + 1, 0);
  const supportedKey = supportedPeriods.join(",");
  const supportedSet = useMemo(() => new Set(supportedPeriods), [supportedKey]);
  const scopeKey = `${subjectType}|${tsCode}|${endDate ?? ""}|${supportedKey}|${supportsNineTurn}`;

  const keyFor = useCallback((period: NineTurnPeriod) => {
    const limit = period === "day" ? 300 : 500;
    return `${subjectType}|${tsCode}|${period}||${endDate ?? ""}|${limit}|`;
  }, [endDate, subjectType, tsCode]);

  const clear = useCallback(() => {
    entriesRef.current.forEach((entry) => entry.controller?.abort());
    entriesRef.current.clear();
    refresh();
  }, []);

  useEffect(() => {
    clear();
    return () => {
      entriesRef.current.forEach((entry) => entry.controller?.abort());
    };
  }, [clear, scopeKey]);

  const stateFor = useCallback((period: NineTurnPeriod): NineTurnLayerViewModel => {
    if (!supportsNineTurn || !supportedSet.has(period)) return unsupportedNineTurnLayer(period);
    return entriesRef.current.get(keyFor(period))?.view ?? idleNineTurnLayer(period);
  }, [keyFor, supportedSet, supportsNineTurn]);

  const ensure = useCallback(async (period: NineTurnPeriod): Promise<void> => {
    if (!supportsNineTurn || !supportedSet.has(period) || endDate === null) return;
    const key = keyFor(period);
    const existing = entriesRef.current.get(key);
    if (existing && existing.view.phase !== "ERROR" && existing.view.phase !== "FORBIDDEN") return;
    entriesRef.current.forEach((entry, entryKey) => {
      if (entryKey !== key && entry.view.phase === "LOADING") {
        entry.controller?.abort();
        entriesRef.current.delete(entryKey);
      }
    });
    const controller = new AbortController();
    const requestId = ++requestSequenceRef.current;
    entriesRef.current.set(key, {
      controller,
      requestId,
      view: {
        ...idleNineTurnLayer(period),
        message: "正在加载九转序列。",
        phase: "LOADING",
      },
    });
    refresh();
    try {
      const response: NineTurnSeriesDto = await load(
        {
          endDate,
          limit: period === "day" ? 300 : 500,
          period,
          subjectType,
          tsCode,
        },
        { signal: controller.signal },
      );
      const current = entriesRef.current.get(key);
      if (controller.signal.aborted || current?.requestId !== requestId) return;
      entriesRef.current.set(key, {
        controller: null,
        requestId,
        view: adaptNineTurnSeries(response, { period, subjectType, tsCode }),
      });
      refresh();
    } catch (error) {
      const current = entriesRef.current.get(key);
      if (controller.signal.aborted || current?.requestId !== requestId) return;
      const forbidden = error instanceof NineTurnApiError && error.status === 403;
      entriesRef.current.set(key, {
        controller: null,
        requestId,
        view: {
          ...idleNineTurnLayer(period),
          canRetry: !forbidden,
          errorCode: error instanceof NineTurnApiError ? error.code : "NT_QUERY_FAILED",
          message: error instanceof Error ? error.message : "九转序列加载失败。",
          phase: forbidden ? "FORBIDDEN" : "ERROR",
        },
      });
      refresh();
    }
  }, [endDate, keyFor, load, subjectType, supportedSet, supportsNineTurn, tsCode]);

  const retry = useCallback(async (period: NineTurnPeriod): Promise<void> => {
    const key = keyFor(period);
    entriesRef.current.get(key)?.controller?.abort();
    entriesRef.current.delete(key);
    await ensure(period);
  }, [ensure, keyFor]);

  return { clear, ensure, retry, stateFor };
}
