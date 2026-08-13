import type { NineTurnMarkerDto, NineTurnPeriod, NineTurnSeriesDto } from "../api/nineTurnApiTypes";

export type NineTurnLayerPhase =
  | "IDLE"
  | "LOADING"
  | "READY"
  | "EMPTY"
  | "SOURCE_EMPTY"
  | "PARTIAL"
  | "ERROR"
  | "FORBIDDEN"
  | "UNSUPPORTED";

export interface NineTurnLayerViewModel {
  canRetry: boolean;
  data: NineTurnSeriesDto | null;
  errorCode: string | null;
  markers: readonly NineTurnMarkerDto[];
  message: string | null;
  period: NineTurnPeriod;
  phase: NineTurnLayerPhase;
}
