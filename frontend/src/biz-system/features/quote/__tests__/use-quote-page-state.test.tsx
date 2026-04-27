import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useQuotePageState } from "../use-quote-page-state";

describe("useQuotePageState", () => {
  it("normalizes ts_code and updates controls", () => {
    const { result } = renderHook(() => useQuotePageState());

    act(() => {
      result.current.setTsCode(" 000300.sh ");
      result.current.setPeriod("week");
      result.current.setAdjustment("backward");
    });

    expect(result.current.state.tsCode).toBe("000300.SH");
    expect(result.current.state.period).toBe("week");
    expect(result.current.state.adjustment).toBe("backward");
  });

  it("forces non-stock adjustment to none", () => {
    const { result } = renderHook(() => useQuotePageState());

    act(() => {
      result.current.setSecurityType("index");
      result.current.setAdjustment("forward");
    });

    expect(result.current.state.securityType).toBe("index");
    expect(result.current.state.adjustment).toBe("none");
  });
});
