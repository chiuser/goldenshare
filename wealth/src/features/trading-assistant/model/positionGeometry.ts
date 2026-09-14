import { geometryFraction } from "./positionPresentation";

export type WeightedTile = { id: string; value: bigint };
export type PositionTile = { id: string; x: number; y: number; width: number; height: number };
/** Binary area layout: all rounding is confined to screen coordinates. */
export function positionTiles(items: readonly WeightedTile[], width = 1000, height = 420): PositionTile[] {
  const positive = items.filter(item => item.value > 0n);
  function split(rows: readonly WeightedTile[], x: number, y: number, w: number, h: number): PositionTile[] {
    if (!rows.length) return [];
    if (rows.length === 1) return [{ id: rows[0].id, x, y, width: w, height: h }];
    const total = rows.reduce((sum, item) => sum + item.value, 0n);
    let left = 0n, cut = 0;
    do { left += rows[cut++].value; } while (cut < rows.length - 1 && left * 2n < total);
    const fraction = geometryFraction(left, total);
    return w >= h ? [...split(rows.slice(0, cut), x, y, w * fraction, h), ...split(rows.slice(cut), x + w * fraction, y, w * (1 - fraction), h)]
      : [...split(rows.slice(0, cut), x, y, w, h * fraction), ...split(rows.slice(cut), x, y + h * fraction, w, h * (1 - fraction))];
  }
  return split(positive, 0, 0, width, height);
}
export function pieSector(start: number, end: number): string {
  const point = (angle: number) => [200 + Math.sin(angle) * 180, 200 - Math.cos(angle) * 180];
  const a = point(start), b = point(end);
  if (end - start >= Math.PI * 2 - 0.000001) return "M 200 20 A 180 180 0 1 1 200 380 A 180 180 0 1 1 200 20 Z";
  return `M 200 200 L ${a[0]} ${a[1]} A 180 180 0 ${end - start > Math.PI ? 1 : 0} 1 ${b[0]} ${b[1]} Z`;
}
