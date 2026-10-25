import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchIndexDetailKline } from "../api/indexDetailApiClient";
import type { IndexPeriodKey } from "../model/indexDetailTypes";
import * as adapter from "./adapter";
import { fetchDailyWaveReview } from "./apiClient";
import { dailyWaveEmptyFixture, dailyWaveKlineFixture, dailyWaveReadyFixture } from "./dailyWaveFixtures.test-support";
import { useDailyWaveReview } from "./useDailyWaveReview";

vi.mock("./apiClient", () => ({ fetchDailyWaveReview: vi.fn() }));
vi.mock("../api/indexDetailApiClient", async importOriginal => ({
  ...await importOriginal<typeof import("../api/indexDetailApiClient")>(), fetchIndexDetailKline: vi.fn(),
}));
type Props = { tsCode: string; activePeriod: IndexPeriodKey };
const initial: Props = { tsCode: "000001.SH", activePeriod: "day" };
function mount(props = initial) { return renderHook((value: Props) => useDailyWaveReview(value), { initialProps: props }); }
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
describe("useDailyWaveReview lifecycle", () => {
  beforeEach(() => {
    vi.mocked(fetchDailyWaveReview).mockResolvedValue(dailyWaveReadyFixture());
    vi.mocked(fetchIndexDetailKline).mockResolvedValue(dailyWaveKlineFixture());
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); vi.useRealTimers(); });

  it("starts closed and never calculates until explicitly enabled", () => {
    const { result } = mount();
    expect(result.current).toMatchObject({ supported: true, enabled: false, phase: "closed", response: null, candles: [], dataKey: null });
    expect(fetchDailyWaveReview).not.toHaveBeenCalled(); expect(fetchIndexDetailKline).not.toHaveBeenCalled();
  });
  it.each<Props>([{ tsCode: "399001.SZ", activePeriod: "day" }, { tsCode: "000001.SH", activePeriod: "m90" }])("does not start unsupported $tsCode/$activePeriod", async props => {
    const { result } = mount(props);
    await act(async () => { result.current.toggle(); result.current.retry(); });
    expect(result.current.supported).toBe(false); expect(result.current.phase).toBe("closed");
    expect(fetchDailyWaveReview).not.toHaveBeenCalled();
  });
  it("requests actual historical dates/1000 with one signal and commits only the verified full result", async () => {
    const pending = deferred<ReturnType<typeof dailyWaveKlineFixture>>();
    vi.mocked(fetchIndexDetailKline).mockReturnValue(pending.promise);
    const { result } = mount();
    await act(async () => result.current.toggle());
    expect(result.current).toMatchObject({ enabled: true, phase: "loading", response: null, candles: [], dataKey: null });
    expect(fetchDailyWaveReview).toHaveBeenCalledTimes(1);
    const signal = vi.mocked(fetchDailyWaveReview).mock.calls[0]![1].signal;
    expect(fetchIndexDetailKline).toHaveBeenCalledWith({ tsCode: "000001.SH", period: "day", startDate: "2023-10-24", endDate: "2023-10-26", limit: 1000 }, { signal });
    await act(async () => pending.resolve(dailyWaveKlineFixture()));
    expect(result.current.phase).toBe("ready");
    expect(result.current.candles.map(candle => candle.close)).toEqual([110, 105, 120]);
    expect(result.current.dataKey).toBe("index:000001.SH:day:wave-review:literal-review");
    expect(signal.aborted).toBe(false);
  });
  it("empty retains its nine-field response and skips real Kline", async () => {
    vi.mocked(fetchDailyWaveReview).mockResolvedValue(dailyWaveEmptyFixture());
    const { result } = mount(); await act(async () => result.current.toggle());
    expect(result.current).toMatchObject({ enabled: true, phase: "empty", response: dailyWaveEmptyFixture(), candles: [], dataKey: null });
    expect(fetchIndexDetailKline).not.toHaveBeenCalled();
  });
  it("a contract failure releases all research data and does not fetch Kline", async () => {
    vi.mocked(fetchDailyWaveReview).mockResolvedValue({ ...dailyWaveReadyFixture(), schemaVersion: 99 });
    const { result } = mount(); await act(async () => result.current.toggle());
    expect(result.current).toMatchObject({ enabled: true, phase: "error", response: null, candles: [], dataKey: null });
    expect(result.current.errorMessage).toContain("校验失败"); expect(fetchIndexDetailKline).not.toHaveBeenCalled();
  });
  it("a Kline mismatch retains only checked facts for explanation, and retry reads everything again", async () => {
    const wrong = dailyWaveKlineFixture(); wrong.bars[0]!.factors.macd.dif = 5.0001;
    vi.mocked(fetchIndexDetailKline).mockResolvedValueOnce(wrong);
    const { result } = mount(); await act(async () => result.current.toggle());
    expect(result.current).toMatchObject({ phase: "mismatch", response: dailyWaveReadyFixture(), candles: [], dataKey: null });
    expect(result.current.errorMessage).toBe("行情与研究结果不一致，暂不显示波段");
    vi.mocked(fetchDailyWaveReview).mockResolvedValue(dailyWaveReadyFixture("retry-review"));
    await act(async () => result.current.retry());
    expect(result.current.phase).toBe("ready"); expect(result.current.dataKey).toContain("retry-review");
    expect(fetchDailyWaveReview).toHaveBeenCalledTimes(2); expect(fetchIndexDetailKline).toHaveBeenCalledTimes(2);
  });
  it.each(["compute", "kline"])("%s errors are not empty/ready and retain no partial response", async stage => {
    if (stage === "compute") vi.mocked(fetchDailyWaveReview).mockRejectedValue(new Error("计算来源失败"));
    else vi.mocked(fetchIndexDetailKline).mockRejectedValue(new Error("K线来源失败"));
    const { result } = mount(); await act(async () => result.current.toggle());
    expect(result.current).toMatchObject({ phase: "error", response: null, candles: [], dataKey: null });
    expect(result.current.errorMessage).toBe("波段划分计算失败，请重试");
  });
  it("close aborts/releases and a late computation cannot bring research back", async () => {
    const pending = deferred<unknown>(); vi.mocked(fetchDailyWaveReview).mockReturnValueOnce(pending.promise);
    const { result } = mount(); await act(async () => result.current.toggle());
    const signal = vi.mocked(fetchDailyWaveReview).mock.calls[0]![1].signal;
    act(() => result.current.close()); expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(dailyWaveReadyFixture("late")));
    expect(result.current).toMatchObject({ enabled: false, phase: "closed", response: null, candles: [], dataKey: null });
    expect(fetchIndexDetailKline).not.toHaveBeenCalled();
  });
  it("a replacement request aborts the old Kline and ignores its later response", async () => {
    const old = deferred<ReturnType<typeof dailyWaveKlineFixture>>();
    vi.mocked(fetchIndexDetailKline).mockReturnValueOnce(old.promise);
    const { result } = mount(); await act(async () => result.current.toggle());
    const signal = vi.mocked(fetchDailyWaveReview).mock.calls[0]![1].signal;
    vi.mocked(fetchDailyWaveReview).mockResolvedValue(dailyWaveReadyFixture("new-request"));
    await act(async () => result.current.retry()); expect(signal.aborted).toBe(true);
    await act(async () => old.resolve(dailyWaveKlineFixture()));
    expect(result.current.dataKey).toContain("new-request");
  });
  it.each<Props>([{ tsCode: "399001.SZ", activePeriod: "day" }, { tsCode: "000001.SH", activePeriod: "m60" }])("changing context closes and aborts $tsCode/$activePeriod", async props => {
    vi.mocked(fetchIndexDetailKline).mockReturnValue(new Promise(() => undefined));
    const { result, rerender } = mount(); await act(async () => result.current.toggle());
    const signal = vi.mocked(fetchDailyWaveReview).mock.calls[0]![1].signal;
    rerender(props);
    expect(signal.aborted).toBe(true); expect(result.current.phase).toBe("closed");
    rerender(initial); expect(result.current.phase).toBe("closed"); expect(fetchDailyWaveReview).toHaveBeenCalledTimes(1);
  });
  it("unmount cancels the whole chain and clears its timer", async () => {
    vi.useFakeTimers(); vi.mocked(fetchDailyWaveReview).mockReturnValue(new Promise(() => undefined));
    const { result, unmount } = mount(); await act(async () => result.current.toggle());
    const signal = vi.mocked(fetchDailyWaveReview).mock.calls[0]![1].signal;
    unmount(); expect(signal.aborted).toBe(true); expect(vi.getTimerCount()).toBe(0);
  });
  it("the original ten-second timer expires while awaiting Kline, without a new ten seconds", async () => {
    vi.useFakeTimers();
    const compute = deferred<unknown>(), kline = deferred<ReturnType<typeof dailyWaveKlineFixture>>();
    vi.mocked(fetchDailyWaveReview).mockReturnValue(compute.promise); vi.mocked(fetchIndexDetailKline).mockReturnValue(kline.promise);
    const { result } = mount(); await act(async () => result.current.toggle());
    await act(async () => vi.advanceTimersByTimeAsync(7800));
    await act(async () => compute.resolve(dailyWaveReadyFixture()));
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(2200));
    expect(result.current).toMatchObject({ phase: "timeout", response: null, candles: [], dataKey: null });
    expect(vi.mocked(fetchDailyWaveReview).mock.calls[0]![1].signal.aborted).toBe(true);
    await act(async () => kline.resolve(dailyWaveKlineFixture()));
    expect(result.current.phase).toBe("timeout");
  });
  it.each([[7900, "ready"], [10000, "timeout"], [10100, "timeout"]] as const)("rejects completion at %ims without relying on timer scheduling", async (end, expected) => {
    let now = 0; vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.mocked(fetchDailyWaveReview).mockImplementation(async () => { now = 7800; return dailyWaveReadyFixture(); });
    vi.mocked(fetchIndexDetailKline).mockImplementation(async () => { now = end; return dailyWaveKlineFixture(); });
    const { result } = mount(); await act(async () => result.current.toggle());
    expect(result.current.phase).toBe(expected);
  });
  it.each(["decode", "match"])("checks original deadline after synchronous %s before committing", async stage => {
    let now = 0; vi.spyOn(performance, "now").mockImplementation(() => now);
    if (stage === "decode") {
      const original = adapter.decodeDailyWaveResponse;
      vi.spyOn(adapter, "decodeDailyWaveResponse").mockImplementation(input => { const result = original(input); now = 10000; return result; });
    } else {
      const original = adapter.matchDailyWaveKline;
      vi.spyOn(adapter, "matchDailyWaveKline").mockImplementation((...args) => { const result = original(...args); now = 10000; return result; });
    }
    const { result } = mount(); await act(async () => result.current.toggle());
    expect(result.current).toMatchObject({ phase: "timeout", response: null, candles: [], dataKey: null });
    if (stage === "decode") expect(fetchIndexDetailKline).not.toHaveBeenCalled();
  });
  it("closing an already ready result releases it; reopening performs a fresh computation", async () => {
    const { result } = mount(); await act(async () => result.current.toggle());
    await waitFor(() => expect(result.current.phase).toBe("ready"));
    act(() => result.current.toggle()); expect(result.current.response).toBeNull();
    vi.mocked(fetchDailyWaveReview).mockResolvedValue(dailyWaveReadyFixture("reopened"));
    await act(async () => result.current.toggle());
    expect(result.current.dataKey).toContain("reopened"); expect(fetchDailyWaveReview).toHaveBeenCalledTimes(2);
  });
});
