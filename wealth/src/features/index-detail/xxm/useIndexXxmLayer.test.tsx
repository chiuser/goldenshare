import {act,renderHook,waitFor} from "@testing-library/react";
import {afterEach,expect,it,vi} from "vitest";
import {fetchXxm} from "./apiClient";
import {useIndexXxmLayer} from "./useIndexXxmLayer";
import {xxmFixture,xxmDebugFixture} from "./xxmFixtures.test-support";
import { decodeXxmDebug } from "../debug/xxmDebugContract";
import type {XxmRequestResult} from "./types";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
vi.mock("./apiClient",async importOriginal=>({...await importOriginal<typeof import('./apiClient')>(),fetchXxm:vi.fn()}));
afterEach(()=>{vi.clearAllMocks();vi.unstubAllEnvs();});
const initial={enabled:true,debug:0 as const,tsCode:"000001.SH",period:"day"};
const resultValue=():XxmRequestResult=>({response:xxmFixture("000001.SH").response,deadline:performance.now()+5000});
it("waits for pending indicators then exposes a source error",()=>{const points=xxmFixture("000001.SH").points.map(p=>({...p,dif:null}));const {result,rerender}=renderHook(({pending})=>useIndexXxmLayer({...initial,points,indicatorsPending:pending}),{initialProps:{pending:true}});expect(result.current.phase).toBe("loading");rerender({pending:false});expect(result.current.phase).toBe("error");expect(fetchXxm).not.toHaveBeenCalled();});
it.each([{ development: false, enabled: true }, { development: true, enabled: false }])("cannot create a primitive or request with development=$development and enabled=$enabled",({ development, enabled })=>{vi.stubEnv("DEV",development);const points=xxmFixture("399001.SZ","m30").points;const {result}=renderHook(()=>useIndexXxmLayer({...initial,tsCode:"399001.SZ",period:"m30",enabled,points,indicatorVersion:1}));expect(result.current.phase).toBe("unsupported");expect(result.current.macdPrimitives).toEqual([]);act(()=>result.current.retry());expect(fetchXxm).not.toHaveBeenCalled();});
it("keeps an unapproved period inactive after cancelling its former owner", async () => {
  let resolve!: (value: XxmRequestResult) => void;
  vi.mocked(fetchXxm).mockImplementationOnce(() => new Promise(accept => { resolve = accept; }));
  const points = xxmFixture("000001.SH").points;
  const { result, rerender } = renderHook(props => useIndexXxmLayer({ ...props, points }), { initialProps: initial });
  await waitFor(() => expect(fetchXxm).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(fetchXxm).mock.calls[0]![1];
  rerender({ ...initial, period: "m15" });
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(resultValue()));
  expect(result.current.phase).toBe("unsupported");
  expect(result.current.data).toBeNull();
  expect(fetchXxm).toHaveBeenCalledTimes(1);
});
it("retries this layer, clears failed data and preserves its primitive",async()=>{vi.mocked(fetchXxm).mockResolvedValueOnce(resultValue()).mockRejectedValueOnce(new Error("源异常"));const points=xxmFixture("000001.SH").points;const {result}=renderHook(()=>useIndexXxmLayer({...initial,points}));await waitFor(()=>expect(result.current.phase).toBe("ready"));expect(result.current.data?.markers).toHaveLength(2);const primitive=result.current.macdPrimitives[0];act(()=>result.current.retry());await waitFor(()=>expect(result.current.phase).toBe("error"));expect(result.current.data).toBeNull();expect(result.current.macdPrimitives[0]).toBe(primitive);});
it("rejects a final commit after the original deadline",async()=>{vi.mocked(fetchXxm).mockResolvedValue({response:xxmFixture("000001.SH").response,deadline:performance.now()-1});const points=xxmFixture("000001.SH").points;const {result}=renderHook(()=>useIndexXxmLayer({...initial,points}));await waitFor(()=>expect(result.current.phase).toBe("error"));expect(result.current.data).toBeNull();});
it("uses new requests for indicator identity and mode, and does not send auxiliary mode without a decoder",async()=>{vi.mocked(fetchXxm).mockResolvedValue(resultValue());const points=xxmFixture("000001.SH").points;const {result,rerender}=renderHook(({indicatorVersion,debug})=>useIndexXxmLayer({...initial,points,indicatorVersion,debug}),{initialProps:{indicatorVersion:null as number|null,debug:0 as 0|1}});await waitFor(()=>expect(result.current.phase).toBe("ready"));rerender({indicatorVersion:2,debug:0});await waitFor(()=>expect(fetchXxm).toHaveBeenCalledTimes(2));rerender({indicatorVersion:2,debug:1});expect(result.current.phase).toBe("unsupported");expect(fetchXxm).toHaveBeenCalledTimes(2);});

const approvedCodes = ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "000300.SH", "000905.SH", "000852.SH", "000510.SH", "000016.SH"];
it.each(approvedCodes.flatMap(tsCode => (["day", "m30", "m60", "m90", "m120"] as const).map(period => ({ tsCode, period }))))("loads nonempty recognition for $tsCode/$period", async ({ tsCode, period }) => {
  const fixture = xxmFixture(tsCode, period);
  if (tsCode === "000510.SH") {
    const start = { day: "2025-11-04", m30: "2025-11-13", m60: "2025-11-12", m90: "2025-11-11", m120: "2025-11-10" }[period];
    expect(fixture.response.source.startTime?.slice(0, 10)).toBe(start);
    expect(fixture.points[0]!.fullDate.slice(0, 10)).toBe("2025-11-13");
  }
  vi.mocked(fetchXxm).mockResolvedValue({ response: fixture.response, deadline: performance.now() + 5000 });
  const { result } = renderHook(() => useIndexXxmLayer({ ...initial, tsCode, period, points: fixture.points, indicatorVersion: period === "day" ? null : 1 }));
  await waitFor(() => expect(result.current.phase).toBe("ready"));
  expect(fetchXxm).toHaveBeenCalledTimes(1);
  expect(vi.mocked(fetchXxm).mock.calls[0]![0]).toMatchObject({ tsCode, period });
  expect(result.current.data?.response.tsCode).toBe(tsCode);
  expect(result.current.data?.response.period).toBe(period);
  expect(result.current.data?.markers).toHaveLength(2);
});

it.each(["success", "failure"] as const)("does not apply an old index's late %s after switching to another eligible index", async terminal => {
  let finish!: (value: XxmRequestResult) => void;
  let fail!: (error: Error) => void;
  const first = xxmFixture("000001.SH", "m30");
  const second = xxmFixture("399001.SZ", "m30");
  vi.mocked(fetchXxm).mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }))
    .mockResolvedValueOnce({ response: second.response, deadline: performance.now() + 5000 });
  const { result, rerender } = renderHook(({ tsCode, points }) => useIndexXxmLayer({ ...initial, tsCode, period: "m30", points, indicatorVersion: 1 }), {
    initialProps: { tsCode: "000001.SH", points: first.points },
  });
  await waitFor(() => expect(fetchXxm).toHaveBeenCalledTimes(1));
  const firstSignal = vi.mocked(fetchXxm).mock.calls[0]![1];
  rerender({ tsCode: "399001.SZ", points: second.points });
  await waitFor(() => expect(result.current.phase).toBe("ready"));
  const current = result.current.data;
  expect(firstSignal.aborted).toBe(true);
  expect(current?.response.tsCode).toBe("399001.SZ");
  await act(async () => {
    if (terminal === "success") finish({ response: first.response, deadline: performance.now() + 5000 });
    else fail(new Error("旧指数请求失败"));
  });
  expect(result.current.phase).toBe("ready");
  expect(result.current.data).toBe(current);
  expect(fetchXxm).toHaveBeenCalledTimes(2);
});

it("changes period and debug owners without reusing a former owner's response", async () => {
  const base = xxmFixture("399001.SZ", "m60");
  const m30 = xxmFixture("399001.SZ", "m30");
  const debug = xxmDebugFixture("399001.SZ", "m30");
  vi.mocked(fetchXxm).mockResolvedValueOnce({ response: base.response, deadline: performance.now() + 5000 })
    .mockResolvedValueOnce({ response: m30.response, deadline: performance.now() + 5000 })
    .mockResolvedValueOnce({ response: debug.response, deadline: performance.now() + 5000 });
  const { result, rerender } = renderHook(props => useIndexXxmLayer(props), { initialProps: {
    ...initial, debug: 0 as 0 | 1, tsCode: "399001.SZ", period: "m60", points: base.points, indicatorVersion: 1, decodeDebug: decodeXxmDebug,
  } });
  await waitFor(() => expect(result.current.phase).toBe("ready"));
  const baseKey = result.current.requestKey;
  rerender({ ...initial, tsCode: "399001.SZ", period: "m30", points: m30.points, indicatorVersion: 1, decodeDebug: decodeXxmDebug });
  await waitFor(() => expect(result.current.data?.response.period).toBe("m30"));
  expect(result.current.requestKey).not.toBe(baseKey);
  const normalKey = result.current.requestKey;
  rerender({ ...initial, tsCode: "399001.SZ", period: "m30", points: debug.points, indicatorVersion: 1, debug: 1 as 0 | 1, decodeDebug: decodeXxmDebug });
  await waitFor(() => expect(result.current.data?.response).toHaveProperty("debug"));
  expect(result.current.requestKey).not.toBe(normalKey);
  expect(fetchXxm).toHaveBeenCalledTimes(3);
  expect(vi.mocked(fetchXxm).mock.calls.map(([request]) => [request.tsCode, request.period, request.debug])).toEqual([
    ["399001.SZ", "m60", undefined], ["399001.SZ", "m30", undefined], ["399001.SZ", "m30", 1],
  ]);
});

it.each((["date", "debug"] as const).flatMap(change => (["success", "failure"] as const).map(terminal => ({ change, terminal }))))("ignores a late $terminal after changing the $change owner", async ({ change, terminal }) => {
  const first = xxmFixture("399001.SZ", "m30");
  const second = change === "debug" ? xxmDebugFixture("399001.SZ", "m30") : xxmFixture("399001.SZ", "m30");
  if (change === "date") {
    const time = "2023-01-13T15:00:00+08:00";
    second.response.points[0]!.time = time;
    second.response.events.forEach(event => { event.time = time; });
    second.response.source.computedThrough = time;
    second.response.meta.responseStart = second.response.meta.responseEnd = time;
    second.response.dataStatus.asOf = time;
    second.points[0]!.fullDate = time;
    second.points[0]!.time = (Date.parse(time) / 1000) as DetailChartPoint["time"];
  }
  let finish!: (value: XxmRequestResult) => void;
  let fail!: (error: Error) => void;
  vi.mocked(fetchXxm).mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }))
    .mockResolvedValueOnce({ response: second.response, deadline: performance.now() + 5000 });
  const { result, rerender } = renderHook(({ points, debug }) => useIndexXxmLayer({ ...initial, tsCode: "399001.SZ", period: "m30", points,
    indicatorVersion: 1, debug, decodeDebug: decodeXxmDebug }), { initialProps: { points: first.points, debug: 0 as 0 | 1 } });
  await waitFor(() => expect(fetchXxm).toHaveBeenCalledTimes(1));
  const oldSignal = vi.mocked(fetchXxm).mock.calls[0]![1];
  rerender({ points: second.points, debug: change === "debug" ? 1 : 0 });
  await waitFor(() => expect(result.current.phase).toBe("ready"));
  expect(oldSignal.aborted).toBe(true);
  const current = result.current.data;
  expect(current?.response).toEqual(second.response);
  await act(async () => {
    if (terminal === "success") finish({ response: first.response, deadline: performance.now() + 5000 });
    else fail(new Error("旧请求失败"));
  });
  expect(result.current.phase).toBe("ready");
  expect(result.current.data).toBe(current);
  expect(fetchXxm).toHaveBeenCalledTimes(2);
});
