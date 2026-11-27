import { useLayoutEffect, useRef, useState } from "react";

import {
  calculatePriceTarget, defaultPriceTargetCoefficients, isPositivePriceTargetNumber,
  type PriceTargetAsset, type PriceTargetDirection, type PriceTargetQuote,
} from "./singleCandlePriceTarget";
import { loadSingleCandlePriceTargetQuote } from "./singleCandlePriceTargetQuote";

type QuoteState =
  | { phase: "idle" | "loading" | "empty" | "error" }
  | { phase: "ready"; quote: PriceTargetQuote };

export function useSingleCandlePriceTarget(asset: PriceTargetAsset) {
  const defaults = defaultPriceTargetCoefficients[asset.kind];
  const [target, setTarget] = useState<PriceTargetDirection>("top");
  const [date, setDate] = useState("");
  const [coefficientText, setCoefficientText] = useState<string>(defaults.top);
  const [quoteState, setQuoteState] = useState<QuoteState>({ phase: "idle" });
  const [result, setResult] = useState<number | null>(null);
  const [resultOutOfRange, setResultOutOfRange] = useState(false);
  const activeRequest = useRef<AbortController | null>(null);

  function cancelRequest() {
    const request = activeRequest.current;
    activeRequest.current = null;
    request?.abort();
  }

  useLayoutEffect(() => cancelRequest, []);

  function clearResult() {
    setResult(null);
    setResultOutOfRange(false);
  }

  function readDate(nextDate: string) {
    cancelRequest();
    clearResult();
    if (!nextDate) {
      setQuoteState({ phase: "idle" });
      return;
    }
    const request = new AbortController();
    activeRequest.current = request;
    setQuoteState({ phase: "loading" });
    void loadSingleCandlePriceTargetQuote(asset, nextDate, request.signal)
      .then((quote) => {
        if (activeRequest.current === request) {
          setQuoteState(quote ? { phase: "ready", quote } : { phase: "empty" });
        }
      })
      .catch(() => {
        if (activeRequest.current === request) setQuoteState({ phase: "error" });
      });
  }

  const coefficient = Number(coefficientText);
  const validCoefficient = isPositivePriceTargetNumber(coefficient);
  const quote = quoteState.phase === "ready" ? quoteState.quote : null;
  const close = quote?.current.close;
  const previousClose = quote?.previous?.close;
  const canCalculate = isPositivePriceTargetNumber(close) && isPositivePriceTargetNumber(previousClose) && validCoefficient;
  const missingPrice = !quote ? null : !isPositivePriceTargetNumber(close) ? "缺少所选交易日收盘价"
    : !isPositivePriceTargetNumber(previousClose) ? "缺少前一交易日收盘价" : null;

  return {
    target, date, coefficientText, validCoefficient, quoteState, missingPrice, canCalculate, result, resultOutOfRange,
    selectDate(nextDate: string) {
      if (date === nextDate) return;
      setDate(nextDate);
      readDate(/^\d{4}-\d{2}-\d{2}$/.test(nextDate) ? nextDate : "");
    },
    selectTarget(nextTarget: PriceTargetDirection) {
      if (target === nextTarget) return;
      setTarget(nextTarget);
      setCoefficientText(defaults[nextTarget]);
      clearResult();
    },
    editCoefficient(value: string) {
      setCoefficientText(value);
      clearResult();
    },
    retry: () => readDate(date),
    calculate() {
      if (!canCalculate) return;
      const value = calculatePriceTarget(close, previousClose, coefficient);
      setResult(value);
      setResultOutOfRange(value === null);
    },
    cancelRequest,
  };
}
