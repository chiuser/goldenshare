import type { CurvePoint } from "../api/generatedContracts";
import { fixedUnits, geometryFraction, positionNumber, positionPercent } from "./positionPresentation";
import type { ReturnMetric } from "./returnSelection";

/** Geometry is derived from exact integers; displayed values always use the original DTO. */
export function returnChart(points: readonly CurvePoint[], metric: ReturnMetric) {
  const values = points.map(p => metric === "RATE" ? p.returnPct : p.profitAmount);
  let low = 0n, high = 0n;
  for (const value of values) if (value !== null) { const n = fixedUnits(value); low = n < low ? n : low; high = n > high ? n : high; }
  if (low === high) { low = -100n; high = 100n; }
  const span = high - low;
  const y = (n: bigint) => 20 + (1 - geometryFraction(n - low, span)) * 310;
  const tickValues = [high, high - span / 4n, high - span / 2n, low + span / 4n, low];
  if (!tickValues.includes(0n)) tickValues.push(0n);
  const decimal = (v: bigint) => `${v < 0n ? "-" : ""}${(v < 0n ? -v : v) / 100n}.${((v < 0n ? -v : v) % 100n).toString().padStart(2,"0")}`;
  return { ticks:[...new Set(tickValues)].sort((a,b) => a > b ? -1 : a < b ? 1 : 0).map(v => ({ y:y(v), zero:v === 0n,
      text:metric === "RATE" ? positionPercent(decimal(v), true) : positionNumber(decimal(v), true) })),
    points:points.map((point, i) => ({ point, x:120 + (points.length > 1 ? i / (points.length - 1) : .5) * 780,
      y:values[i] === null ? null : y(fixedUnits(values[i]!)) })) };
}
