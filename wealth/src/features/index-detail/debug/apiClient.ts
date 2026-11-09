import {
  fetchIndexDetail,
  type fetchIndexDetailPageInit,
  type fetchIndexDetailKline,
  type fetchIndexDetailWeights,
} from "../api/indexDetailApiClient";
import { IndexDetailRequestScheduler } from "../api/indexDetailRequestScheduler";
import { assert, record } from "../xxm/adapter";
import { sendXxm, XXM_TIMEOUT_MS, type fetchXxm } from "../xxm/apiClient";
import { sendForecast, type fetchForecast } from "../xxm-forecast/apiClient";
import { adaptForecast, type ForecastDecodeOptions } from "../xxm-forecast/adapter";
import { decodeForecastDebug } from "./forecastDebugContract";
import { decodeDebugXxmResponse } from "./xxmAdapter";

export const debugRequests = new IndexDetailRequestScheduler();
export const fetchDebugPageInit: typeof fetchIndexDetailPageInit = (params, options = {}) =>
  fetchIndexDetail("debug/page-init", params, options);
export const fetchDebugKline: typeof fetchIndexDetailKline = (params, options = {}) =>
  fetchIndexDetail("debug/kline", params, options);
export const fetchDebugWeights: typeof fetchIndexDetailWeights = (params, options = {}) =>
  fetchIndexDetail("debug/weights", params, options);

export const fetchDebugXxm: typeof fetchXxm = (params, signal) =>
  debugRequests.run("xxm", () => sendXxm(params, signal, performance.now() + XXM_TIMEOUT_MS,
    "debug/", decodeDebugXxmResponse), signal);

export function decodeDebugForecast(raw: unknown, options: ForecastDecodeOptions) {
  assert(record(raw) && Object.hasOwn(raw, "debug"));
  const { debug, ...fields } = raw;
  const response = adaptForecast(fields, options);
  const details = decodeForecastDebug(debug, { response, period: options.period, asOf: options.asOf, check: options.check });
  options.check();
  return { ...response, debug: details };
}

export const fetchDebugForecast: typeof fetchForecast = (tsCode, period, asOf, signal) =>
  debugRequests.run("forecast", () => sendForecast(tsCode, period, asOf, signal,
    performance.now() + XXM_TIMEOUT_MS, "debug/", decodeDebugForecast), signal);
