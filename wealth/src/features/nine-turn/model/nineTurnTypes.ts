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

export type NineTurnDisplayPeriod = NineTurnPeriod | "week" | "month" | "1";

export interface NineTurnLayerViewModel {
  canRetry: boolean;
  data: NineTurnSeriesDto | null;
  errorCode: string | null;
  markers: readonly NineTurnMarkerDto[];
  message: string | null;
  period: NineTurnDisplayPeriod;
  phase: NineTurnLayerPhase;
}
