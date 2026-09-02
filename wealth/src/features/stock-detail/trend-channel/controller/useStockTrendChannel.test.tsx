import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useStockTrendChannel } from "./useStockTrendChannel";

describe("useStockTrendChannel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("does not request until ensure and aborts the old stock request on switch", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    vi.stubGlobal("fetch", fetchMock);
    const hook = renderHook(
      ({ tsCode }) => useStockTrendChannel({ enabled: true, endDate: "2026-08-27", tsCode }),
      { initialProps: { tsCode: "000001.SZ" } },
    );

    expect(fetchMock).not.toHaveBeenCalled();
    act(() => hook.result.current.ensure());
    act(() => hook.result.current.ensure());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const signal = (fetchMock.mock.calls[0]?.[1] as RequestInit | undefined)?.signal;
    expect(signal?.aborted).toBe(false);

    hook.rerender({ tsCode: "600000.SH" });
    await waitFor(() => expect(signal?.aborted).toBe(true));
    expect(hook.result.current.data).toBeNull();
    expect(hook.result.current.phase).toBe("idle");
  });

  it("keeps capability false at zero requests", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const hook = renderHook(() => useStockTrendChannel({
      enabled: false,
      endDate: "2026-08-27",
      tsCode: "000001.SZ",
    }));

    act(() => hook.result.current.ensure());
    expect(hook.result.current.phase).toBe("unavailable");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
