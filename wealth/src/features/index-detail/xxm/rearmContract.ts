import type { XxmPeriod, XxmRearmRecord } from "./types";

const keys = ["id", "direction", "bottomHistoryId", "structureEventId", "structureConfirmedAt", "structureRoute",
  "segmentStart", "nearestPriceGate", "reference", "disappearedAt", "observedThrough", "status", "endedAt", "endReason"];

/** Contract validation only; all prices and signal decisions come from Biz. */
export function validRearmRecord(r: XxmRearmRecord, period: XxmPeriod, through: string): boolean {
  const stamp = (v: unknown): v is string => {
    if (typeof v !== "string") return false;
    if (period === "day") return /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v))
      && new Date(v).toISOString().slice(0, 10) === v;
    return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$/.test(v) && Number.isFinite(Date.parse(v))
      && new Date(Date.parse(v) + 8 * 60 * 60 * 1000).toISOString().replace(".000Z", "+08:00") === v;
  };
  if (!r || typeof r !== "object" || Object.keys(r).length !== keys.length || Object.keys(r).some(k => !keys.includes(k))
    || ![r.id, r.bottomHistoryId, r.structureEventId].every(v => typeof v === "string" && v.length > 0)
    || r.direction !== "BOTTOM" || r.structureRoute !== "dif_turn"
    || !Number.isFinite(r.nearestPriceGate) || r.nearestPriceGate <= 0 || !r.reference
    || Object.keys(r.reference).sort().join() !== "dif,endTime,price,startTime"
    || !Number.isFinite(r.reference.price) || r.reference.price <= 0 || !Number.isFinite(r.reference.dif)
    || ![r.reference.startTime, r.reference.endTime, r.segmentStart, r.structureConfirmedAt,
      r.disappearedAt, r.observedThrough, through].every(stamp)
    || !(r.reference.startTime <= r.reference.endTime && r.reference.endTime < r.segmentStart
      && r.segmentStart <= r.structureConfirmedAt && r.structureConfirmedAt < r.disappearedAt
      && r.disappearedAt <= r.observedThrough && r.observedThrough <= through)) return false;
  if (r.status === "WAITING") return r.endedAt === null && r.endReason === null && r.observedThrough === through;
  const reasons = { REACTIVATED: ["price_requalified"], INVALIDATED: ["reference_dif_break"], SEGMENT_ENDED: ["color_flip", "zero"] };
  return r.status in reasons && stamp(r.endedAt) && r.disappearedAt < r.endedAt && r.endedAt === r.observedThrough
    && reasons[r.status as keyof typeof reasons].includes(r.endReason ?? "");
}
