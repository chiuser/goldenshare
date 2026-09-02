import { useCallback, useEffect, useId, useRef, useState } from "react";

import {
  fetchStockSearch,
  type StockSearchApiError,
} from "../api/stockSearchApi";
import {
  buildStockSearchOptions,
  type StockSearchOption,
} from "../api/stockSearchAdapter";

export const STOCK_SEARCH_DEBOUNCE_MS = 500;
export const STOCK_SEARCH_TIMEOUT_MS = 2000;

export type StockSearchState =
  | { kind: "idle" }
  | { kind: "closed"; keyword: string }
  | { kind: "debouncing"; keyword: string }
  | { kind: "loading"; keyword: string }
  | {
      kind: "ready";
      keyword: string;
      options: StockSearchOption[];
      activeIndex: number;
    }
  | { kind: "empty"; keyword: string }
  | { kind: "error"; keyword: string; message: string };

interface UseStockSearchControllerOptions {
  onSelect: (tsCode: string) => void;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function useStockSearchController({
  onSelect,
}: UseStockSearchControllerOptions) {
  const [inputValue, setInputValue] = useState("");
  const [state, setState] = useState<StockSearchState>({ kind: "idle" });
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const stateRef = useRef<StockSearchState>(state);
  const inputValueRef = useRef(inputValue);
  const debounceTimerRef = useRef<number | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const pendingCommitRef = useRef(false);
  const optionElementsRef = useRef<Array<HTMLElement | null>>([]);
  const reactId = useId().replaceAll(":", "");
  const listboxId = `stock-search-listbox-${reactId}`;

  const updateState = useCallback((nextState: StockSearchState) => {
    stateRef.current = nextState;
    setState(nextState);
  }, []);

  const clearDebounce = useCallback(() => {
    if (debounceTimerRef.current !== null) {
      window.clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
  }, []);

  const invalidateRequest = useCallback(() => {
    requestIdRef.current += 1;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  }, []);

  const commitOption = useCallback(
    (option: StockSearchOption) => {
      clearDebounce();
      invalidateRequest();
      pendingCommitRef.current = false;
      inputValueRef.current = option.tsCode;
      setInputValue(option.tsCode);
      updateState({ kind: "closed", keyword: option.tsCode });
      onSelect(option.tsCode);
    },
    [clearDebounce, invalidateRequest, onSelect, updateState],
  );

  const runSearch = useCallback(
    (keyword: string, options: { commitFirst?: boolean } = {}) => {
      clearDebounce();
      invalidateRequest();
      const currentRequestId = requestIdRef.current;
      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      if (options.commitFirst) pendingCommitRef.current = true;
      updateState({ kind: "loading", keyword });

      let timedOut = false;
      const timeoutId = window.setTimeout(() => {
        timedOut = true;
        abortController.abort();
      }, STOCK_SEARCH_TIMEOUT_MS);

      fetchStockSearch(keyword, { signal: abortController.signal })
        .then((payload) => {
          if (currentRequestId !== requestIdRef.current) return;
          const searchOptions = buildStockSearchOptions(payload);
          if (searchOptions.length === 0) {
            pendingCommitRef.current = false;
            updateState({ kind: "empty", keyword });
            return;
          }
          if (pendingCommitRef.current) {
            commitOption(searchOptions[0]);
            return;
          }
          updateState({
            kind: "ready",
            keyword,
            options: searchOptions,
            activeIndex: 0,
          });
        })
        .catch((error: unknown) => {
          if (currentRequestId !== requestIdRef.current) return;
          if (isAbortError(error) && !timedOut) return;
          pendingCommitRef.current = false;
          const message = timedOut
            ? "搜索暂不可用，请稍后重试"
            : error instanceof Error
              ? (error as StockSearchApiError).message
              : "搜索暂不可用，请稍后重试";
          updateState({ kind: "error", keyword, message });
        })
        .finally(() => {
          window.clearTimeout(timeoutId);
          if (currentRequestId === requestIdRef.current) {
            abortControllerRef.current = null;
          }
        });
    },
    [clearDebounce, commitOption, invalidateRequest, updateState],
  );

  const handleInputChange = useCallback(
    (rawValue: string) => {
      const keyword = rawValue.trim().toUpperCase();
      inputValueRef.current = keyword;
      setInputValue(keyword);
      clearDebounce();
      invalidateRequest();
      pendingCommitRef.current = false;
      optionElementsRef.current = [];
      if (!keyword) {
        updateState({ kind: "idle" });
        return;
      }
      updateState({ kind: "debouncing", keyword });
      debounceTimerRef.current = window.setTimeout(() => {
        debounceTimerRef.current = null;
        runSearch(keyword);
      }, STOCK_SEARCH_DEBOUNCE_MS);
    },
    [clearDebounce, invalidateRequest, runSearch, updateState],
  );

  const closeMenu = useCallback(() => {
    clearDebounce();
    invalidateRequest();
    pendingCommitRef.current = false;
    const keyword = inputValueRef.current;
    updateState(keyword ? { kind: "closed", keyword } : { kind: "idle" });
  }, [clearDebounce, invalidateRequest, updateState]);

  const handleKeyDown = useCallback(
    (key: string): boolean => {
      const currentState = stateRef.current;
      if (key === "Escape") {
        if (["loading", "ready", "empty", "error"].includes(currentState.kind)) {
          closeMenu();
          return true;
        }
        return false;
      }
      if (key === "ArrowDown" || key === "ArrowUp") {
        if (currentState.kind !== "ready" || currentState.options.length === 0) {
          return false;
        }
        const offset = key === "ArrowDown" ? 1 : -1;
        const activeIndex =
          (currentState.activeIndex + offset + currentState.options.length)
          % currentState.options.length;
        updateState({ ...currentState, activeIndex });
        return true;
      }
      if (key !== "Enter") return false;
      if (currentState.kind === "idle") return false;
      if (currentState.kind === "ready") {
        commitOption(currentState.options[currentState.activeIndex]);
        return true;
      }
      if (currentState.kind === "loading") {
        pendingCommitRef.current = true;
        return true;
      }
      runSearch(inputValueRef.current, { commitFirst: true });
      return true;
    },
    [closeMenu, commitOption, runSearch, updateState],
  );

  const setActiveIndex = useCallback(
    (activeIndex: number) => {
      const currentState = stateRef.current;
      if (currentState.kind !== "ready") return;
      if (activeIndex < 0 || activeIndex >= currentState.options.length) return;
      updateState({ ...currentState, activeIndex });
    },
    [updateState],
  );

  const selectIndex = useCallback(
    (index: number) => {
      const currentState = stateRef.current;
      if (currentState.kind !== "ready") return;
      const option = currentState.options[index];
      if (option) commitOption(option);
    },
    [commitOption],
  );

  const setOptionElement = useCallback(
    (index: number, element: HTMLElement | null) => {
      optionElementsRef.current[index] = element;
    },
    [],
  );

  useEffect(() => {
    if (state.kind !== "ready") return;
    optionElementsRef.current[state.activeIndex]?.scrollIntoView?.({
      block: "nearest",
    });
  }, [state]);

  useEffect(
    () => () => {
      clearDebounce();
      invalidateRequest();
      pendingCommitRef.current = false;
    },
    [clearDebounce, invalidateRequest],
  );

  const menuOpen = ["loading", "ready", "empty", "error"].includes(state.kind);
  const activeOptionId =
    state.kind === "ready"
      ? `${listboxId}-option-${state.activeIndex}`
      : undefined;

  return {
    inputValue,
    state,
    isFocused,
    menuOpen,
    inputRef,
    listboxId,
    activeOptionId,
    handleInputChange,
    handleFocus: () => setIsFocused(true),
    handleBlur: () => {
      setIsFocused(false);
      closeMenu();
    },
    handleKeyDown,
    setActiveIndex,
    selectIndex,
    setOptionElement,
  };
}
