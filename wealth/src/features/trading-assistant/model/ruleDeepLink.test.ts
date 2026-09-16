import { describe, expect, it } from "vitest";
import { readRuleDeepLink } from "./ruleDeepLink";
import { buildLoginPath, readRedirectPath } from "../../../app/routes/routerState";

describe("notification detail links", () => {
  const id = "12345678-1234-1234-1234-123456789abc";
  it("preserves type and ID through login without granting permission", () => {
    const path = `/wealth/market/trading-assistant?ruleType=ALERT&ruleId=${id}`;
    expect(readRedirectPath(buildLoginPath(path).split("?")[1])).toBe(path);
    expect(readRuleDeepLink(path.split("?")[1])).toEqual({kind:"ALERT",ruleId:id});
  });
  it.each(["", "?ruleType=ROBOT&ruleId=" + id, "?ruleType=PLAN&ruleId=not-an-id",
    `?ruleType=PLAN&ruleType=ALERT&ruleId=${id}`, `?ruleType=PLAN&ruleId=${id}&ruleId=${id}`])("rejects malformed link %s", value => {
    expect(readRuleDeepLink(value)).toBeNull();
  });
});
