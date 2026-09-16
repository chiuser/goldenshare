import type { CheckRecord, RuleRow, NotificationSummary, Conditions } from "../api/generatedContracts";

export function conditionText({ priceCondition: price, volumeCondition: volume }: Conditions): string {
  const parts: string[] = [];
  if (price) parts.push(price.operator === "LTE" ? `前复权价格 ≤ ${price.upper || "待填写"} 元`
    : price.operator === "GTE" ? `前复权价格 ≥ ${price.lower || "待填写"} 元`
    : `前复权价格 ${price.lower || "待填写"} — ${price.upper || "待填写"} 元（含边界）`);
  if (volume) parts.push(`当日累计成交量 ${volume.operator === "GTE" ? "≥" : "≤"} ${volume.thresholdLots || "待填写"} 手`);
  return parts.length ? parts.join("，且 ") : "请至少启用一个条件";
}

/** Display-only HALF_UP. The exact source text and server verdict stay intact. */
export function evidenceNumber(value: string): string {
  const [whole, fraction = ""] = value.split(".");
  const digits = fraction.padEnd(3, "0");
  const cents = BigInt(whole) * 100n + BigInt(digits.slice(0, 2)) + (digits[2] >= "5" ? 1n : 0n);
  return `${cents / 100n}.${(cents % 100n).toString().padStart(2, "0")}`;
}

export const ruleTime = (value: string | null) => value === null ? "—" : new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
}).format(new Date(value));
export const checkLabel = (state: RuleRow["checkStatus"]) => ({ PENDING: "待验证", CHECKING: "验证中", WAITING_DATA: "等待数据", FAILED: "验证失败", COMPLETED: "验证完成" })[state];
export const resultLabel = (row: RuleRow) => row.ruleStatus === "CLOSED" ? "已关闭" : row.finalResult ? row.finalResult.triggered ? "已触发" : "未触发" : row.checkStatus === "PENDING" ? "—" : "待确认";
export const notificationLabel = (row: NotificationSummary) => ({ NOT_ENABLED: "未开启", NOT_CREATED: "等待验证", PENDING: "待发送", SENDING: "发送中", SUCCEEDED: "发送成功", FAILED: "发送失败", UNKNOWN: "结果待核对" })[row.state];
export const checkTitle = (row: CheckRecord) => `第 ${row.checkNo} 次 · ${checkLabel(row.status)} · ${ruleTime(row.startedAt)}`;
