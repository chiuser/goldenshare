import { expect, it } from "vitest";
import { writeOperation } from "./writeOperation";
import { parseContract } from "../api/contractValidation";
import { evidenceNumber, conditionText } from "./rulePresentation";

it("formats evidence to two digits without changing exact source or verdict", () => {
  expect(evidenceNumber("999999999999999999.995")).toBe("1000000000000000000.00");
  expect(evidenceNumber("9.0")).toBe("9.00");
  expect(evidenceNumber("0.0049")).toBe("0.00");
  expect(conditionText({ priceCondition: { operator: "LTE", upper: "10.00" }, volumeCondition: { operator: "GTE", thresholdLots: "10.00" } })).toContain("且 当日累计成交量 ≥ 10.00 手");
});

it("uses the original protocol for creation and rule maintenance, never ledger targets", () => {
  const ruleId = crypto.randomUUID(), accountId = crypto.randomUUID();
  expect(writeOperation("PLAN_CREATE", { scopeType:"RULE_CREATE",ruleType:"PLAN",accountId,tsCode:"000001.SZ" }).path).toBe("/plans");
  expect(writeOperation("RULE_CLOSE", { scopeType:"RULE",ruleType:"ALERT",ruleId }).path).toBe(`/alerts/${ruleId}/close`);
  expect(() => writeOperation("ALERT_CREATE", { scopeType:"RULE_CREATE",ruleType:"PLAN",accountId,tsCode:"000001.SZ" })).toThrow();
  expect(() => writeOperation("RULE_CLOSE", { scopeType:"ACCOUNT_LEDGER",accountId })).toThrow();
  expect(() => parseContract("RuleCreateScope", { scopeType:"RULE_CREATE",ruleType:"ALERT",accountId,tsCode:"000001.SZ" })).toThrow();
});
