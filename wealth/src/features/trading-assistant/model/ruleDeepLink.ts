import type { RuleKind } from "../api/rulesApi";

/** A link selects a view only. Ownership is checked by the authenticated detail API. */
export function readRuleDeepLink(search: string): { kind: RuleKind; ruleId: string } | null {
  const params = new URLSearchParams(search), kind = params.get("ruleType"), ruleId = params.get("ruleId");
  if (params.getAll("ruleType").length !== 1 || params.getAll("ruleId").length !== 1
      || (kind !== "PLAN" && kind !== "ALERT") || !ruleId
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(ruleId)) return null;
  return { kind, ruleId };
}
