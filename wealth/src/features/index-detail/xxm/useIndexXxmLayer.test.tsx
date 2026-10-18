import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchXxm } from "./apiClient";
import { useIndexXxmLayer } from "./useIndexXxmLayer";
import { xxmFixture } from "./xxmFixtures.test-support";
import type { XxmResponse } from "./types";

vi.mock("./apiClient", () => ({ fetchXxm: vi.fn() }));
afterEach(() => vi.clearAllMocks());

describe("XXM request isolation", () => {
  it("waits for pending MACD, then fails explicitly when the source is missing", () => {
    const { points } = xxmFixture();
    const incomplete = points.map(point => ({ ...point, dif: null }));
    const { result, rerender } = renderHook(({ pending }) => useIndexXxmLayer({
      tsCode: "000001.SH", period: "m60", points: incomplete, indicatorsPending: pending,
    }), { initialProps: { pending: true } });
    expect(result.current.phase).toBe("loading");
    rerender({ pending: false });
    expect(result.current.phase).toBe("error");
    expect(result.current.errorMessage).toContain("MACD 数据缺失");
    expect(fetchXxm).not.toHaveBeenCalled();
  });
  it("never requests unsupported code/period and invalidates late response after switching", async () => {
    const { points, response } = xxmFixture();
    let resolve: (value: XxmResponse) => void = () => {};
    vi.mocked(fetchXxm).mockImplementationOnce(() => new Promise(res => { resolve = res; }));
    const { result, rerender } = renderHook(({ code, period }) => useIndexXxmLayer({ tsCode: code, period, points }),
      { initialProps: { code: "000001.SH", period: "day" } });
    await waitFor(() => expect(fetchXxm).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(fetchXxm).mock.calls[0]![1];
    rerender({ code: "399001.SZ", period: "day" });
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(response));
    expect(result.current.phase).toBe("unsupported");
    rerender({ code: "000001.SH", period: "m30" });
    expect(fetchXxm).toHaveBeenCalledTimes(1);
    expect(result.current.macdPrimitives).toEqual([]);
  });
  it("loads a real-shaped response independently and retries only this layer", async () => {
    const { points, response } = xxmFixture();
    vi.mocked(fetchXxm).mockResolvedValueOnce(response).mockRejectedValueOnce(new Error("源异常"));
    const { result } = renderHook(() => useIndexXxmLayer({ tsCode: "000001.SH", period: "day", points }));
    await waitFor(() => expect(result.current.phase).toBe("ready"));
    expect(result.current.data?.markers).toHaveLength(2);
    const primitive = result.current.macdPrimitives[0];
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.data).toBeNull();
    expect(result.current.macdPrimitives[0]).toBe(primitive);
  });
});

it("rejects an old detector response and accepts the a1 response on retry", async () => {
  const { points, response } = xxmFixture();
  const old = { ...response, algorithmVersion: "xxm-direction-v0.1" };
  vi.mocked(fetchXxm).mockResolvedValueOnce(old).mockResolvedValueOnce(response);
  const { result } = renderHook(() => useIndexXxmLayer({ tsCode: "000001.SH", period: "day", points }));
  await waitFor(() => expect(result.current.phase).toBe("error"));
  expect(result.current.data).toBeNull();
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.phase).toBe("ready"));
  expect(result.current.data?.response.algorithmVersion).toBe("xxm-direction-v0.1-r2");
});
