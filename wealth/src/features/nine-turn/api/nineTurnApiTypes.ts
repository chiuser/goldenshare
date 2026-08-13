export type NineTurnSubjectType = "stock" | "index";
export type NineTurnPeriod = "day" | "5" | "15" | "30" | "60" | "90" | "120";
export type NineTurnDirection = "UP" | "DOWN";
export type NineTurnSequenceNumber = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;

export interface NineTurnMarkerDto {
  completed: boolean;
  direction: NineTurnDirection;
  sequenceNumber: NineTurnSequenceNumber;
  tradeDate: string;
  tradeTime: string | null;
}

export interface NineTurnDataStatusDto {
  code: string | null;
  expectedEndDate: string | null;
  message: string | null;
  observedEndDate: string | null;
  status: "READY" | "DELAYED" | "EMPTY" | "PARTIAL";
}

export interface NineTurnMetaDto {
  comparisonLag: 4;
  endDate: string;
  formulaVersion: 1;
  hasMore: boolean;
  limit: number;
  markerCount: number;
  matchedRowCount: number;
  missingRowCount: number;
  nextCursor: string | null;
  observedEndDate: string | null;
  observedStartDate: string | null;
  signalThreshold: 9;
  sourceRowCount: number;
  startDate: string | null;
}

export interface NineTurnSeriesDto {
  dataStatus: NineTurnDataStatusDto;
  debugInfo: Record<string, unknown> | null;
  latestMarker: NineTurnMarkerDto | null;
  markers: NineTurnMarkerDto[];
  meta: NineTurnMetaDto;
  period: NineTurnPeriod;
  subjectType: NineTurnSubjectType;
  tsCode: string;
}
