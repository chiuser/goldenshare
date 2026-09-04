import { isDailyInsightDate } from "../api/sectorDailyInsightContract";
import type { DailyInsightUrlState } from "../api/sectorDailyInsightTypes";

export function parseSectorDailyInsightUrlState(search: string): { ok: true; value: DailyInsightUrlState } | { ok: false; message: string } {
  const query = new URLSearchParams(search);
  for (const key of new Set(query.keys())) {
    if (!["market", "tradeDate", "level"].includes(key) || query.getAll(key).length !== 1) return { ok: false, message: "每日洞察页面参数不正确，请检查链接。" };
  }
  if (query.has("market") && query.get("market") !== "CN_A") return { ok: false, message: "当前只支持 A 股市场。" };
  const tradeDate = query.get("tradeDate");
  if (tradeDate !== null && !isDailyInsightDate(tradeDate)) return { ok: false, message: "交易日必须使用有效的 YYYY-MM-DD 日期。" };
  const level = query.get("level") ?? "1";
  if (!["1", "2", "3"].includes(level)) return { ok: false, message: "洞察层级只支持一级、二级或三级行业。" };
  return { ok: true, value: { market: "CN_A", tradeDate, level: Number(level) as 1 | 2 | 3 } };
}
export function buildSectorDailyInsightSearch(state: DailyInsightUrlState): string {
  const query = new URLSearchParams();
  if (state.tradeDate) query.set("tradeDate", state.tradeDate);
  if (state.level !== 1) query.set("level", String(state.level));
  return query.size ? `?${query}` : "";
}
