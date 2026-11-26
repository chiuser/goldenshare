import { directionClass, directionFromNumber } from "../../../../shared/lib/marketDirection";

const MISSING = "—";

export function yuanToYi(value: number): number {
  return value / 100_000_000;
}

export function formatTurnover(value: number | null): string {
  return value === null ? MISSING : yuanToYi(value).toFixed(2);
}

export function formatEtfPrice(value: number): string {
  return value.toFixed(3);
}

export function formatEtfPriceChange(value: number) {
  const digits = Math.abs(value).toFixed(2);
  const signed = digits === "0.00" ? 0 : value;
  const sign = signed < 0 ? "−" : signed > 0 ? "+" : "";
  return { text: `${sign}${digits}%`, className: directionClass(directionFromNumber(signed)) };
}

export function formatEtfRankChange(value: number | null) {
  const text = value === null ? MISSING : value === 0 ? "持平" : `${value > 0 ? "↑" : "↓"} ${Math.abs(value)}`;
  return { text, className: directionClass(directionFromNumber(value)) };
}
