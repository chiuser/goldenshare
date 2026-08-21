export const ETA_SAMPLE_INTERVAL_MS = 10_000;

export type EtaSample = {
  nodeId: number;
  unitDone: number;
  unitTotal: number;
  monotonicMs: number;
  wallClockMs: number;
};

export type EtaEstimate =
  | { status: "warming_up" }
  | { status: "unavailable" }
  | { status: "completed" }
  | { status: "ready"; estimatedAtMs: number; etaSeconds: number };

export function calculateEtaEstimate(current: EtaSample, previous: EtaSample | null): EtaEstimate {
  if (current.unitTotal <= 0) {
    return { status: "unavailable" };
  }
  if (current.unitDone >= current.unitTotal) {
    return { status: "completed" };
  }
  if (!previous) {
    return { status: "warming_up" };
  }
  if (
    previous.nodeId !== current.nodeId ||
    previous.unitTotal !== current.unitTotal ||
    current.unitDone < previous.unitDone
  ) {
    return { status: "warming_up" };
  }

  const elapsedSeconds = (current.monotonicMs - previous.monotonicMs) / 1000;
  const completedSincePrevious = current.unitDone - previous.unitDone;
  if (elapsedSeconds <= 0 || completedSincePrevious <= 0) {
    return { status: "unavailable" };
  }

  const unitsPerSecond = completedSincePrevious / elapsedSeconds;
  const remainingUnits = Math.max(current.unitTotal - current.unitDone, 0);
  const etaSeconds = remainingUnits / unitsPerSecond;
  return {
    status: "ready",
    etaSeconds,
    estimatedAtMs: current.wallClockMs + etaSeconds * 1000,
  };
}
