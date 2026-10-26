import type { DailyWaveReadyResponse } from "./types";
import type { DailyWaveMarkerIssue, DailyWaveMarkerInput } from "./markerGeometry";

export type DailyWaveSegment = DailyWaveReadyResponse["segments"][number];
export type DailyWaveEndpoint = NonNullable<DailyWaveSegment["start"]>;
export interface DailyWaveExplanation {
  segment: DailyWaveSegment;
  colorStart: string;
  colorEnd: string;
  reasons: string[];
}
export interface DailyWaveEndpointFact {
  segment: DailyWaveSegment;
  role: "start" | "end";
}
export interface DailyWavePresentation {
  markers: DailyWaveMarkerInput[];
  explanations: DailyWaveExplanation[];
  byDate: ReadonlyMap<string, readonly DailyWaveEndpointFact[]>;
  unavailableEndpointCount: number;
  spaceUnavailableEndpointCount: number;
}

/** Consume published eligibility; never select another endpoint or hide issues. */
export function buildDailyWavePresentation(
  response: DailyWaveReadyResponse,
  layoutIssues: readonly DailyWaveMarkerIssue[] = [],
): DailyWavePresentation {
  const colors = new Map(response.colorSegments.map((color) => [color.id, color]));
  const mappings = new Map(response.mappings.map((mapping) => [mapping.priceSegmentId, mapping]));
  const drawableFacts: DailyWaveEndpointFact[] = [];
  const byDate = new Map<string, DailyWaveEndpointFact[]>();
  const explanations: DailyWaveExplanation[] = [];
  const inside = (day: string) => day >= response.observationStart && day <= response.observationEnd;

  for (const segment of response.segments) {
    const color = colors.get(segment.sourceColorSegmentId)!;
    const reasons = new Set(segment.issues.map((issue) => describeIssue(issue)));
    for (const issue of mappings.get(segment.id)?.issues ?? []) reasons.add(describeIssue(issue));
    if (!color.isLeftComplete) reasons.add("最左侧柱色区间不完整，前面行情有限。");
    if (!segment.generated) reasons.add("尚不能确定这段行情的起始和终止K线。");
    else {
      if (!segment.isEnded) reasons.add("这段行情尚未结束，暂不画终止三角。");
      if (segment.isEnded && [segment.startValidity, segment.endValidity, segment.endpointValidity].some((v) => v !== "VALID"))
        reasons.add("起始和终止K线未通过检查，暂不画正常的一对三角。");
      for (const role of ["start", "end"] as const) {
        const endpoint = segment[role];
        if (!endpoint) continue;
        const existing = byDate.get(endpoint.date) ?? [];
        existing.push({ segment, role });
        byDate.set(endpoint.date, existing);
        if (!inside(endpoint.date)) reasons.add(`${role === "start" ? "起始" : "终止"}K线在本次观察范围之外，保留实际日期${endpoint.date}。`);
      }
    }

    const startKnown = segment.startKnownAt !== null && segment.startKnownAt <= response.asOf;
    const startAllowed = segment.generated && segment.start !== null && segment.startValidity === "VALID" && startKnown;
    const pairAllowed = startAllowed && segment.isEnded && segment.end !== null
      && segment.endValidity === "VALID" && segment.endpointValidity === "VALID"
      && segment.endKnownAt !== null && segment.endKnownAt <= response.asOf;
    const roles = segment.isEnded ? pairAllowed ? ["start", "end"] as const : [] : startAllowed ? ["start"] as const : [];
    for (const role of roles) {
      const endpoint = segment[role]!;
      if (!inside(endpoint.date)) continue;
      drawableFacts.push({ segment, role });
    }
    for (const issue of layoutIssues) if (issue.segmentIds.includes(segment.id))
      reasons.add(issue.reason === "SPACE_UNAVAILABLE"
        ? `起止K线${issue.date}空间不足，暂未绘制；计算日期保留。`
        : `起止K线${issue.date}暂时无法取得绘图坐标，计算日期保留。`);
    if (reasons.size) explanations.push({ segment, colorStart: color.startDate, colorEnd: color.endDate, reasons: [...reasons] });
  }
  explanations.sort((a, b) => a.colorStart.localeCompare(b.colorStart) || a.segment.id.localeCompare(b.segment.id));
  return {
    markers: buildDailyWaveMarkers(drawableFacts),
    explanations,
    byDate,
    unavailableEndpointCount: new Set(layoutIssues.map((issue) => `${issue.date}|${issue.direction}`)).size,
    spaceUnavailableEndpointCount: new Set(layoutIssues.filter((issue) => issue.reason === "SPACE_UNAVAILABLE").map((issue) => `${issue.date}|${issue.direction}`)).size,
  };
}

/** Map every eligible start/end to its triangle direction, then share drawn positions. */
function buildDailyWaveMarkers(facts: readonly DailyWaveEndpointFact[]): DailyWaveMarkerInput[] {
  const knownAt = new Map(facts.map(({ segment }) => [segment.id, segment.startKnownAt!]));
  const grouped = new Map<string, { date: string; direction: DailyWaveMarkerInput["direction"]; segmentIds: Set<string> }>();
  for (const { segment, role } of facts) {
    const date = segment[role]!.date;
    const direction = role === "start" ? segment.direction : segment.direction === "UP" ? "DOWN" : "UP";
    const key = `${date}|${direction}`;
    const marker = grouped.get(key) ?? { date, direction, segmentIds: new Set<string>() };
    marker.segmentIds.add(segment.id);
    grouped.set(key, marker);
  }
  return [...grouped.values()].map((marker) => ({ ...marker,
    segmentIds: [...marker.segmentIds].sort((a, b) => knownAt.get(a)!.localeCompare(knownAt.get(b)!) || a.localeCompare(b)),
  })).sort((a, b) => a.date.localeCompare(b.date) || a.direction.localeCompare(b.direction));
}

function describeIssue(issue: { message: string; dates: readonly string[] }): string {
  return issue.dates.length ? `${issue.message}（${issue.dates.join("、")}）` : issue.message;
}
