import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useXxmForecast } from "./useXxmForecast";
import { fetchForecast } from "./apiClient";
import { XxmForecastCard } from "./XxmForecastCard";
import { forecastFixture, forecastDebugFixture, forecastReactivationFixture } from "./forecastFixtures.test-support";
import { ForecastDebugDetails } from "../debug/ForecastDebugDetails";
import type { ForecastDebugResponse, ForecastResponse } from "./types";
const renderForecastDetails = (response: ForecastResponse) => "debug" in response ? <ForecastDebugDetails response={response as ForecastDebugResponse} /> : null;
import type { ForecastPeriod, ForecastRequestResult, ForecastRows } from "./types";

vi.mock("./apiClient", () => ({ fetchForecast: vi.fn() }));
const mocked = vi.mocked(fetchForecast);
const initial = { active: false, tsCode: "399001.SZ", minutes: true, enabled: true };
const wrapped = (tsCode: string, period: ForecastPeriod) => ({ response: forecastFixture(tsCode, period), deadline: performance.now() + 5000 });
beforeEach(() => mocked.mockReset());
afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs(); vi.restoreAllMocks(); });

it("shows the backend price ranges before the necessary comparisons for both outcomes", () => {
  const response = forecastReactivationFixture();
  render(renderForecastDetails(response));
  fireEvent.click(screen.getByText("计算依据"));
  const direct = screen.getByText(/· SIGNAL_DISAPPEARED · NEAR/).parentElement!;
  const far = screen.getByText(/· STRUCTURE_DISAPPEARED_AND_DULL_FORMED · FAR/).parentElement!;
  const label = "必要比较（结果以适用收盘区间为准）";
  expect(within(direct).getByText("适用收盘区间")).toBeVisible();
  expect(within(direct).getByText("收盘≥90 且<160").nextElementSibling).toHaveTextContent(label);
  expect(within(far).getByText("收盘>0 且<90").nextElementSibling).toHaveTextContent(label);
  expect(screen.getByText(/另有1段临界价格待核验/)).toBeVisible();
});

it("loads five rows only after activation and retries only the failed m30 row", async () => {
  const pending: Array<{ tsCode: string; period: ForecastPeriod; resolve: (value: ForecastRequestResult) => void; reject: (error: Error) => void }> = [];
  mocked.mockImplementation((tsCode, period) => new Promise((resolve, reject) => pending.push({ tsCode, period, resolve, reject })));
  const { result, rerender } = renderHook(props => useXxmForecast(props), { initialProps: initial });
  expect(mocked).not.toHaveBeenCalled();
  rerender({ ...initial, active: true });
  await waitFor(() => expect(pending).toHaveLength(5));
  expect(pending.map(({ tsCode, period }) => [tsCode, period])).toEqual([
    ["399001.SZ", "day"], ["399001.SZ", "m30"], ["399001.SZ", "m60"], ["399001.SZ", "m90"], ["399001.SZ", "m120"],
  ]);
  await act(async () => {
    for (const request of pending) {
      if (request.period === "m30") request.reject(new Error("source failed"));
      else request.resolve(wrapped(request.tsCode, request.period));
    }
  });
  expect(result.current.rows.day.phase).toBe("ready");
  expect(result.current.rows.m30).toMatchObject({ phase: "error", response: null, error: "source failed" });
  expect(result.current.rows.m60.phase).toBe("ready");
  const readyDay = result.current.rows.day.response;
  act(() => result.current.retry("m30"));
  expect(pending).toHaveLength(6);
  expect(pending[5]).toMatchObject({ tsCode: "399001.SZ", period: "m30" });
  await act(async () => pending[5]!.resolve(wrapped("399001.SZ", "m30")));
  expect(result.current.rows.m30.phase).toBe("ready");
  expect(result.current.rows.day.response).toBe(readyDay);
});

it.each([{ dev: false, enabled: true }, { dev: true, enabled: false }])("does not request when DEV=$dev and enabled=$enabled", ({ dev, enabled }) => {
  vi.stubEnv("DEV", dev);
  const { result } = renderHook(() => useXxmForecast({ ...initial, active: true, enabled }));
  act(() => result.current.retry("day"));
  expect(mocked).not.toHaveBeenCalled();
});

it("loads only the supported day row through the supplied request function", async () => {
  const load = vi.fn().mockResolvedValue({ response: forecastDebugFixture("399001.SZ"), deadline: performance.now() + 5000 });
  const { result } = renderHook(() => useXxmForecast({ ...initial, active: true, minutes: false }, load));
  await waitFor(() => expect(result.current.rows.day.phase).toBe("ready"));
  for (const period of ["m30", "m60", "m90", "m120"] as const) expect(result.current.rows[period].phase).toBe("unsupported");
  expect(load).toHaveBeenCalledTimes(1);
  expect(mocked).not.toHaveBeenCalled();
});

it("aborts and ignores late values on deactivation", async () => {
  let resolve!: (value: ForecastRequestResult) => void;
  mocked.mockImplementation(() => new Promise(done => { resolve = done; }));
  const { result, rerender } = renderHook(props => useXxmForecast(props), { initialProps: { ...initial, active: true, minutes: false } });
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
  const signal = mocked.mock.calls[0]![3];
  rerender({ ...initial, active: false, minutes: false });
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(wrapped("399001.SZ", "day")));
  expect(result.current.rows.day.response).toBeNull();
});

it("uses the original deadline for the final commit and clears failed old responses", async () => {
  mocked.mockResolvedValue({ response: forecastFixture("399001.SZ"), deadline: performance.now() - 1 });
  const { result } = renderHook(() => useXxmForecast({ ...initial, active: true, minutes: false }));
  await waitFor(() => expect(result.current.rows.day.phase).toBe("error"));
  expect(result.current.rows.day.response).toBeNull();
});

it("does not poll historical dates and keeps the date on manual retry", async () => {
  vi.useFakeTimers();
  const asOf = "2023-01-10";
  mocked.mockImplementation(async tsCode => ({ response: forecastFixture(tsCode, "day", asOf), deadline: performance.now() + 5000 }));
  const { result, unmount } = renderHook(() => useXxmForecast({ ...initial, active: true, minutes: false, historicalDate: asOf }));
  await act(async () => { await Promise.resolve(); });
  expect(result.current.rows.day.phase).toBe("ready");
  await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
  expect(mocked).toHaveBeenCalledTimes(1);
  await act(async () => { result.current.retry("day"); await Promise.resolve(); });
  expect(mocked.mock.calls.map(call => call[2])).toEqual([asOf, asOf]);
  unmount(); expect(vi.getTimerCount()).toBe(0);
});

it("passes historical day and minute asOf values without calculating the next m30 endpoint", async () => {
  const historicalDate = "2023-01-10";
  mocked.mockImplementation(async (tsCode, period, asOf) => ({ response: forecastFixture(tsCode, period, asOf), deadline: performance.now() + 5000 }));
  const { result } = renderHook(() => useXxmForecast({ ...initial, active: true, historicalDate }));
  await waitFor(() => expect(result.current.rows.m30.phase).toBe("ready"));
  expect(mocked.mock.calls.map(call => call.slice(0, 3))).toEqual([
    ["399001.SZ", "day", "2023-01-10"],
    ["399001.SZ", "m30", "2023-01-10T15:00:00+08:00"],
    ["399001.SZ", "m60", "2023-01-10T15:00:00+08:00"],
    ["399001.SZ", "m90", "2023-01-10T15:00:00+08:00"],
    ["399001.SZ", "m120", "2023-01-10T15:00:00+08:00"],
  ]);
  expect(result.current.rows.m30.response?.targetEndpoint).toBe("2023-01-11T10:00:00+08:00");
});

it("polls latest by the backend interval and stops on deactivation", async () => {
  vi.useFakeTimers();
  mocked.mockImplementation(async (tsCode, period) => wrapped(tsCode, period));
  const { rerender, unmount } = renderHook(props => useXxmForecast(props), { initialProps: { ...initial, active: true, minutes: false } });
  await act(async () => { await Promise.resolve(); });
  expect(mocked).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
  expect(mocked).toHaveBeenCalledTimes(2);
  rerender({ ...initial, active: false, minutes: false });
  await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
  expect(mocked).toHaveBeenCalledTimes(2);
  unmount(); expect(vi.getTimerCount()).toBe(0);
});

it("renders five rows in order using backend text and retries the selected m30 row", () => {
  const periods = ["day", "m30", "m60", "m90", "m120"] as const;
  const rows = Object.fromEntries(periods.map(period => [period, { phase: "ready", response: forecastFixture("399001.SZ", period), error: "" }])) as ForecastRows;
  rows.day.response = forecastDebugFixture("399001.SZ");
  rows.m30 = { phase: "error", response: null, error: "网络异常" };
  const retry = vi.fn();
  const { container, rerender } = render(<XxmForecastCard rows={rows} retry={retry} />);
  expect(Array.from(container.querySelectorAll("[data-period]"), node => node.getAttribute("data-period"))).toEqual(["day", "m30", "m60", "m90", "m120"]);
  expect(screen.getByText("30 分钟")).toBeVisible();
  expect(screen.getAllByText("只适用下一根完成收盘。", { selector: "small" })[0]).toBeVisible();
  expect(screen.queryByText("计算依据")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重试30 分钟关键点预判" }));
  expect(retry).toHaveBeenCalledTimes(1);
  expect(retry).toHaveBeenCalledWith("m30");
  rerender(<XxmForecastCard rows={rows} retry={retry} renderDetails={renderForecastDetails} />);
  expect(screen.getByText("计算依据")).toBeVisible();
  expect(screen.queryByText(/评分|可信度|买入|卖出/)).not.toBeInTheDocument();
});

it.each([false, true])("renders the ready m30 row's backend text and requested auxiliary details, debug=%s", debug => {
  const periods = ["day", "m30", "m60", "m90", "m120"] as const;
  const rows = Object.fromEntries(periods.map(period => [period, { phase: "ready", response: forecastFixture("399001.SZ", period), error: "" }])) as ForecastRows;
  const response = debug ? forecastDebugFixture("399001.SZ", "m30") : forecastFixture("399001.SZ", "m30");
  rows.m30 = { phase: "ready", response, error: "" };
  const { container } = render(<XxmForecastCard rows={rows} retry={vi.fn()} renderDetails={debug ? renderForecastDetails : undefined} />);
  const element = container.querySelector<HTMLElement>('[data-period="m30"]')!;
  const row = within(element);
  expect(element).toHaveAttribute("data-phase", "ready");
  expect(row.getByText("30 分钟")).toBeVisible();
  expect(row.getByText(response.display.statusLabel)).toBeVisible();
  expect(row.getByText(response.display.targetText)).toBeVisible();
  expect(row.getByText(response.display.conditionsText)).toBeVisible();
  expect(row.getByText(response.display.asOfText)).toBeVisible();
  expect(row.queryByRole("button", { name: "重试30 分钟关键点预判" })).not.toBeInTheDocument();
  if (debug) {
    fireEvent.click(row.getByText("计算依据"));
    const details = row.getByLabelText("关键点预判计算依据");
    expect(details).toHaveAttribute("open");
    expect(within(details).getByText(`截至${response.computedThrough}，目标${response.targetEndpoint}；精度full_float`)).toBeVisible();
  } else {
    expect(row.queryByText("计算依据")).not.toBeInTheDocument();
    expect(row.queryByLabelText("关键点预判计算依据")).not.toBeInTheDocument();
  }
});

// The actual owner/mode effects run; only the HTTP client is replaced.
it.each([
  { change: "index", late: "success" }, { change: "index", late: "failure" },
  { change: "date", late: "success" }, { change: "date", late: "failure" },
  { change: "debug", late: "success" }, { change: "debug", late: "failure" },
] as const)("ignores a late $late after changing $change and accepts only the new result", async ({ change, late }) => {
  const pending: Array<{ resolve: (value: ForecastRequestResult) => void; reject: (error: Error) => void }> = [];
  mocked.mockImplementation(() => new Promise((resolve, reject) => pending.push({ resolve, reject })));
  const props = { ...initial, active: true, minutes: false, historicalDate: undefined as string | undefined, load: fetchForecast };
  const otherLoad: typeof fetchForecast = (...args) => fetchForecast(...args);
  const { result, rerender } = renderHook(({ load, ...p }) => useXxmForecast(p, load), { initialProps: props });
  await waitFor(() => expect(pending).toHaveLength(1));
  const oldSignal = mocked.mock.calls[0]![3];
  const next = { ...props, ...(change === "index" ? { tsCode: "000688.SH" } : change === "date" ? { historicalDate: "2023-01-10" } : { load: otherLoad }) };
  rerender(next);
  await waitFor(() => expect(pending).toHaveLength(2));
  expect(oldSignal.aborted).toBe(true);
  const response = change === "debug" ? forecastDebugFixture(next.tsCode) : forecastFixture(next.tsCode, "day", next.historicalDate);
  await act(async () => pending[1]!.resolve({ response, deadline: performance.now() + 5000 }));
  expect(result.current.rows.day.response).toEqual(response);
  expect(mocked.mock.calls[1]!.slice(0, 3)).toEqual([next.tsCode, "day", next.historicalDate]);
  await act(async () => {
    if (late === "success") pending[0]!.resolve(wrapped(props.tsCode, "day"));
    else pending[0]!.reject(new Error("old request failed"));
  });
  expect(result.current.rows.day).toEqual({ phase: "ready", response, error: "" });
});

it("cancels queued rows while hidden and resumes them when visible", async () => {
  let visibility: DocumentVisibilityState = "hidden";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  const signals: AbortSignal[] = [];
  const pending: Array<(value: ForecastRequestResult) => void> = [];
  mocked.mockImplementation((_code, _period, _asOf, signal) => {
    signals.push(signal);
    return new Promise(resolve => pending.push(resolve));
  });
  const { result } = renderHook(() => useXxmForecast({ ...initial, active: true, minutes: false }));
  expect(mocked).not.toHaveBeenCalled();
  act(() => { visibility = "visible"; document.dispatchEvent(new Event("visibilitychange")); });
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
  act(() => { visibility = "hidden"; document.dispatchEvent(new Event("visibilitychange")); });
  expect(signals[0]!.aborted).toBe(true);
  await act(async () => pending[0]!(wrapped("399001.SZ", "day")));
  expect(result.current.rows.day.response).toBeNull();
  act(() => { visibility = "visible"; document.dispatchEvent(new Event("visibilitychange")); });
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
  await act(async () => pending[1]!(wrapped("399001.SZ", "day")));
  expect(result.current.rows.day.phase).toBe("ready");
});
