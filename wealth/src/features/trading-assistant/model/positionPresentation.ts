import type { PositionRow } from "../api/generatedContracts";

/** Validated fixed-point text only. Never convert account amounts to Number. */
export function fixedUnits(value: string): bigint {
  const negative = value.startsWith("-");
  const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
  return BigInt(whole + fraction.padEnd(2, "0")) * (negative ? -1n : 1n);
}
export function positionNumber(value: string | null, signed = false): string {
  if (value === null) return "—";
  const units = fixedUnits(value), absolute = units < 0n ? -units : units;
  return (units < 0n ? "-" : signed && units > 0n ? "+" : "")
    + (absolute / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + (absolute % 100n).toString().padStart(2, "0");
}
export const positionPercent = (value: string | null, signed = false) => value === null ? "—" : positionNumber(value, signed) + "%";
export const positionQuantity = (value: string | null) => value === null ? "未知" : value.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
export const profitTone = (value: string | null) => value === null ? "unknown" : fixedUnits(value) > 0n ? "up" : fixedUnits(value) < 0n ? "down" : "flat";
export type PositionSort = "marketValue" | "stockValueWeightPct" | "holdingProfitAmount" | "holdingReturnPct";
export function sortPositions(rows: readonly PositionRow[], field: PositionSort, descending = true) {
  return [...rows].sort((a, b) => {
    const x = a[field], y = b[field];
    if (x === null || y === null) return x === y ? a.stockRef.tsCode.localeCompare(b.stockRef.tsCode) : x === null ? 1 : -1;
    const difference = fixedUnits(x) - fixedUnits(y);
    return difference === 0n ? a.stockRef.tsCode.localeCompare(b.stockRef.tsCode) : (difference > 0n ? 1 : -1) * (descending ? -1 : 1);
  });
}

/** Bounded pixel geometry only, never a returned or displayed business percentage. */
export function geometryFraction(value: bigint, total: bigint): number {
  return total > 0n ? Number(value * 1_000_000n / total) / 1_000_000 : 0;
}
