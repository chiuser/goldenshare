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

export type StockSearchState<Option extends StockSearchOption = StockSearchOption> =
  | { kind: "idle" }
  | { kind: "closed"; keyword: string }
  | { kind: "debouncing"; keyword: string }
  | { kind: "loading"; keyword: string }
  | {
      kind: "ready";
      keyword: string;
      options: Option[];
      activeIndex: number;
    }
  | { kind: "empty"; keyword: string }
  | { kind: "error"; keyword: string; message: string };

export interface SearchInteraction {
  debounceMs: number; timeoutMs: number; maxKeyword: number; enterFirst: boolean;
}
export const DEFAULT_SEARCH_INTERACTION: SearchInteraction = {
  debounceMs: STOCK_SEARCH_DEBOUNCE_MS, timeoutMs: STOCK_SEARCH_TIMEOUT_MS, maxKeyword: 32, enterFirst: true,
};
export type CandidateLoader<Option extends StockSearchOption> = (input: { keyword: string; signal: AbortSignal }) => Promise<Option[]>;
type Selection<Option> = { onSelect: (tsCode: string) => void; onSelectOption?: never }
  | { onSelectOption: (option: Option) => void; onSelect?: never };
type UseStockSearchControllerOptions<Option extends StockSearchOption> = Selection<Option> & {
  loadCandidates?: CandidateLoader<Option>; interaction?: SearchInteraction;
};
const defaultLoader: CandidateLoader<StockSearchOption> = async ({ keyword, signal }) =>
  buildStockSearchOptions(await fetchStockSearch(keyword, { signal }));

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function useStockSearchController<Option extends StockSearchOption = StockSearchOption>({
  onSelect, onSelectOption, loadCandidates, interaction = DEFAULT_SEARCH_INTERACTION,
}: UseStockSearchControllerOptions<Option>) {
  const loader = loadCandidates ?? (defaultLoader as CandidateLoader<Option>);
  const [inputValue, setInputValue] = useState("");
  const [state, setState] = useState<StockSearchState<Option>>({ kind: "idle" });
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const stateRef = useRef<StockSearchState<Option>>(state);
  const inputValueRef = useRef(inputValue);
  const debounceTimerRef = useRef<number | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const pendingCommitRef = useRef(false);
  const optionElementsRef = useRef<Array<HTMLElement | null>>([]);
  const reactId = useId().replaceAll(":", "");
  const listboxId = `stock-search-listbox-${reactId}`;

  const updateState = useCallback((nextState: StockSearchState<Option>) => {
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
    (option: Option) => {
      clearDebounce();
      invalidateRequest();
      pendingCommitRef.current = false;
      inputValueRef.current = option.tsCode;
      setInputValue(option.tsCode);
      updateState({ kind: "closed", keyword: option.tsCode });
      if (onSelectOption) onSelectOption(option); else onSelect(option.tsCode);
    },
    [clearDebounce, invalidateRequest, onSelect, onSelectOption, updateState],
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
      }, interaction.timeoutMs);

      loader({ keyword, signal: abortController.signal })
        .then((searchOptions) => {
          if (currentRequestId !== requestIdRef.current) return;
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
            activeIndex: interaction.enterFirst ? 0 : -1,
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
    [clearDebounce, commitOption, invalidateRequest, updateState, loader, interaction],
  );

  const handleInputChange = useCallback(
    (rawValue: string) => {
      const keyword = rawValue.trim().toUpperCase().slice(0, interaction.maxKeyword);
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
      }, interaction.debounceMs);
    },
    [clearDebounce, invalidateRequest, runSearch, updateState, interaction],
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
        const activeIndex = currentState.activeIndex < 0
          ? (key === "ArrowDown" ? 0 : currentState.options.length - 1)
          : (currentState.activeIndex + offset + currentState.options.length) % currentState.options.length;
        updateState({ ...currentState, activeIndex });
        return true;
      }
      if (key !== "Enter") return false;
      if (currentState.kind === "idle") return false;
      if (currentState.kind === "ready") {
        if (currentState.activeIndex < 0) return false;
        commitOption(currentState.options[currentState.activeIndex]);
        return true;
      }
      if (!interaction.enterFirst) return false;
      if (currentState.kind === "loading") {
        pendingCommitRef.current = true;
        return true;
      }
      runSearch(inputValueRef.current, { commitFirst: true });
      return true;
    },
    [closeMenu, commitOption, runSearch, updateState, interaction],
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
    state.kind === "ready" && state.activeIndex >= 0
      ? `${listboxId}-option-${state.activeIndex}`
      : undefined;

  const resetInput = useCallback((value: string) => {
    clearDebounce(); invalidateRequest(); pendingCommitRef.current = false;
    inputValueRef.current = value; setInputValue(value);
    updateState(value ? { kind: "closed", keyword: value } : { kind: "idle" });
  }, [clearDebounce, invalidateRequest, updateState]);

  return {
    inputValue,
    resetInput,
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
