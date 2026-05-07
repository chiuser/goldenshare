import type { MarketDirection } from "../model/market";

export function directionFromNumber(value: number | null | undefined): MarketDirection {
  if (value == null) return "UNKNOWN";
  if (value > 0) return "UP";
  if (value < 0) return "DOWN";
  return "FLAT";
}

export function directionClass(direction: MarketDirection): string {
  if (direction === "UP") return "up";
  if (direction === "DOWN") return "down";
  if (direction === "FLAT") return "flat";
  return "secondary";
}
