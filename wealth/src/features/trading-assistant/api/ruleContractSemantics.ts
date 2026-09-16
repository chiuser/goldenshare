import type { Conditions, FinalResult, NotificationSummary, RuleRow, RuleCreateScope, CreatePlanInput } from "./generatedContracts";

const cents = (value: string) => { const [whole, part = ""] = value.split("."); return BigInt(whole + part.padEnd(2, "0")); };
export function validRuleCombination(title: unknown, value: Record<string, unknown>): boolean {
  if (typeof title !== "string") return true;
  if (title === "PriceBetween" || title === "PriceBetweenEvidence") return cents(value.lower as string) <= cents(value.upper as string);
  if (["Conditions", "CreateRuleInput", "CreatePlanInput", "CreateAlertInput", "CreatePlanCommand", "CreateAlertCommand", "ReviseConditionsCommand"].includes(title)) {
    const row = value as unknown as Conditions;
    if (row.priceCondition === null && row.volumeCondition === null) return false;
  }
  if (title === "CreatePlanInput" || title === "CreatePlanCommand") {
    const row = value as unknown as CreatePlanInput;
    if ((row.notifyEnabled ?? false) !== (row.robotId !== null && row.robotId !== undefined)) return false;
  }
  if (title === "RuleCreateScope") {
    const row = value as unknown as RuleCreateScope;
    return (row.ruleType === "PLAN") === (row.accountId !== null && row.accountId !== undefined);
  }
  if (["RuleRow", "PlanRow", "AlertRow", "PlanDetail", "AlertDetail"].includes(title)) {
    const row = value as unknown as RuleRow;
    if ((row.ruleStatus === "ENDED") !== (row.finalResult !== null)) return false;
  }
  if (title === "FinalResult") {
    const row = value as unknown as FinalResult;
    if (!row.triggered) return row.firstTriggeredAt === null;
    const checks = [row.priceCheck, row.volumeCheck].filter(check => check !== null);
    return row.ruleVersionId !== null && row.firstTriggeredAt !== null && checks.length > 0
      && checks.every(check => check.satisfied && check.checkpointAt === row.firstTriggeredAt);
  }
  if (title === "NotificationSummary") {
    const row = value as unknown as NotificationSummary;
    if (["NOT_ENABLED", "NOT_CREATED"].includes(row.state)) return row.notificationId === null && row.stateVersion === null && !row.canRetry;
    return row.notificationId !== null && row.stateVersion !== null && row.robotId !== null && (!row.canRetry || row.state === "FAILED");
  }
  return true;
}
