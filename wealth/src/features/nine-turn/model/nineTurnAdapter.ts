import type { NineTurnPeriod, NineTurnSeriesDto } from "../api/nineTurnApiTypes";
import type { NineTurnDisplayPeriod, NineTurnLayerViewModel } from "./nineTurnTypes";

export function adaptNineTurnSeries(
  response: NineTurnSeriesDto,
  {
    period,
    subjectType,
    tsCode,
  }: {
    period: NineTurnPeriod;
    subjectType: NineTurnSeriesDto["subjectType"];
    tsCode: string;
  },
): NineTurnLayerViewModel {
  if (
    response.subjectType !== subjectType ||
    response.tsCode !== tsCode ||
    response.period !== period ||
    response.meta.comparisonLag !== 4 ||
    response.meta.signalThreshold !== 9 ||
    response.meta.formulaVersion !== 1
  ) {
    throw new Error("九转响应身份或公式合同不一致。");
  }
  if (
    !isNonNegativeInteger(response.meta.sourceRowCount) ||
    !isNonNegativeInteger(response.meta.matchedRowCount) ||
    !isNonNegativeInteger(response.meta.missingRowCount) ||
    response.meta.matchedRowCount + response.meta.missingRowCount !== response.meta.sourceRowCount ||
    response.meta.markerCount !== response.markers.length ||
    response.meta.markerCount > response.meta.matchedRowCount
  ) {
    throw new Error("九转响应数量合同不一致。");
  }
  let previousTimeKey: number | string | null = null;
  for (const marker of response.markers) {
    validateMarker(marker, period);
    const currentTimeKey = markerTimeKey(marker, period);
    if (previousTimeKey !== null && compareTimeKey(currentTimeKey, previousTimeKey) <= 0) {
      throw new Error("九转 marker 时间键必须严格升序且唯一。");
    }
    previousTimeKey = currentTimeKey;
  }
  if (response.latestMarker !== null) {
    validateMarker(response.latestMarker, period);
    const lastMarker = response.markers.at(-1);
    if (!lastMarker || markerIdentity(lastMarker) !== markerIdentity(response.latestMarker)) {
      throw new Error("九转 latestMarker 与当前窗口最新 marker 不一致。");
    }
  }

  const phase = resolvePhase(response);
  return {
    canRetry: false,
    data: response,
    errorCode: response.dataStatus.code,
    markers: response.markers,
    message: resolveMessage(response, phase),
    period,
    phase,
  };
}

function validateMarker(
  marker: NineTurnSeriesDto["markers"][number],
  period: NineTurnPeriod,
): void {
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(marker.tradeDate) ||
    (marker.direction !== "UP" && marker.direction !== "DOWN") ||
    !Number.isInteger(marker.sequenceNumber) ||
    marker.sequenceNumber < 1 ||
    marker.sequenceNumber > 9 ||
    marker.completed !== (marker.sequenceNumber === 9)
  ) {
    throw new Error("九转 marker 合同不一致。");
  }
  if (period === "day") {
    if (marker.tradeTime !== null) throw new Error("九转 marker 时间合同不一致。");
    return;
  }
  if (
    marker.tradeTime === null ||
    marker.tradeTime.slice(0, 10) !== marker.tradeDate ||
    !Number.isFinite(Date.parse(marker.tradeTime))
  ) {
    throw new Error("九转 marker 时间合同不一致。");
  }
}

function markerTimeKey(
  marker: NineTurnSeriesDto["markers"][number],
  period: NineTurnPeriod,
): number | string {
  return period === "day" ? marker.tradeDate : Date.parse(marker.tradeTime!);
}

function compareTimeKey(left: number | string, right: number | string): number {
  if (typeof left === "number" && typeof right === "number") return left - right;
  return String(left).localeCompare(String(right));
}

function markerIdentity(marker: NineTurnSeriesDto["markers"][number]): string {
  return [
    marker.tradeDate,
    marker.tradeTime ?? "",
    marker.direction,
    marker.sequenceNumber,
    marker.completed,
  ].join("|");
}

function isNonNegativeInteger(value: number): boolean {
  return Number.isInteger(value) && value >= 0;
}

export function idleNineTurnLayer(period: NineTurnPeriod): NineTurnLayerViewModel {
  return {
    canRetry: false,
    data: null,
    errorCode: null,
    markers: [],
    message: null,
    period,
    phase: "IDLE",
  };
}

export function unsupportedNineTurnLayer(period: NineTurnDisplayPeriod): NineTurnLayerViewModel {
  return {
    canRetry: false,
    data: null,
    errorCode: null,
    markers: [],
    message: "当前周期不提供九转序列。",
    period,
    phase: "UNSUPPORTED",
  };
}

function resolvePhase(response: NineTurnSeriesDto): NineTurnLayerViewModel["phase"] {
  if (response.dataStatus.status === "EMPTY") return "SOURCE_EMPTY";
  if (response.dataStatus.status === "PARTIAL") return "PARTIAL";
  if (response.dataStatus.status === "DELAYED") {
    return response.markers.length > 0 ? "PARTIAL" : "SOURCE_EMPTY";
  }
  return response.markers.length > 0 ? "READY" : "EMPTY";
}

function resolveMessage(
  response: NineTurnSeriesDto,
  phase: NineTurnLayerViewModel["phase"],
): string | null {
  if (response.dataStatus.message) return response.dataStatus.message;
  if (phase === "EMPTY") return "当前窗口暂无九转标记。";
  return null;
}
