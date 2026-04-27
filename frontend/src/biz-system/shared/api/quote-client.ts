import { apiRequest } from "../../../shared/api/client";

import type {
  QuoteKlineQuery,
  QuoteKlineResponse,
  QuotePageInitResponse,
  QuoteRelatedInfoResponse,
  QuoteSecurityType,
} from "./quote-types";

function appendParam(params: URLSearchParams, key: string, value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") {
    return;
  }
  params.set(key, String(value));
}

export async function fetchQuotePageInit(tsCode: string, securityType: QuoteSecurityType) {
  const params = new URLSearchParams();
  appendParam(params, "ts_code", tsCode);
  appendParam(params, "security_type", securityType);
  return apiRequest<QuotePageInitResponse>(`/api/v1/quote/detail/page-init?${params.toString()}`);
}

export async function fetchQuoteKline(query: QuoteKlineQuery) {
  const params = new URLSearchParams();
  appendParam(params, "ts_code", query.ts_code);
  appendParam(params, "security_type", query.security_type);
  appendParam(params, "period", query.period);
  appendParam(params, "adjustment", query.adjustment);
  appendParam(params, "limit", query.limit ?? 240);
  return apiRequest<QuoteKlineResponse>(`/api/v1/quote/detail/kline?${params.toString()}`);
}

export async function fetchQuoteRelatedInfo(tsCode: string, securityType: QuoteSecurityType) {
  const params = new URLSearchParams();
  appendParam(params, "ts_code", tsCode);
  appendParam(params, "security_type", securityType);
  return apiRequest<QuoteRelatedInfoResponse>(`/api/v1/quote/detail/related-info?${params.toString()}`);
}
