import type { AlertsQuery, PlansQuery } from "./generatedContracts";
import { InvalidTradingAssistantResponse, parseContract } from "./contractValidation";
import { request } from "./tradingAssistantApi";

export type RuleKind = "PLAN" | "ALERT";
export const rulePath = (kind: RuleKind, id?: string) => (kind === "PLAN" ? "/plans" : "/alerts") + (id ? `/${encodeURIComponent(id)}` : "");
const queryText = (query: object) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value !== null && value !== undefined) params.set(key, String(value));
  return params.toString();
};
export async function getRules(kind: RuleKind, query: PlansQuery | AlertsQuery, signal: AbortSignal) {
  const validated = kind === "PLAN" ? parseContract("PlansQuery", query) : parseContract("AlertsQuery", query);
  return request(rulePath(kind) + "?" + queryText(validated), kind === "PLAN" ? "PlansResponse" : "AlertsResponse", { signal });
}
export async function getRule(kind: RuleKind, id: string, signal?: AbortSignal) {
  const detail = await request(rulePath(kind, id), kind === "PLAN" ? "PlanDetail" : "AlertDetail", { signal });
  if (detail.ruleId !== id) throw new InvalidTradingAssistantResponse();
  return detail;
}
export const getRuleChecks = (kind: RuleKind, id: string, cursor: string | null, signal: AbortSignal) =>
  request(rulePath(kind, id) + "/checks?" + queryText({ cursor }), "CheckHistoryResponse", { signal });
export const getRuleVersions = (kind: RuleKind, id: string, cursor: string | null, signal: AbortSignal) =>
  request(rulePath(kind, id) + "/condition-versions?" + queryText({ cursor }), "ConditionHistoryResponse", { signal });
