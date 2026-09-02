import type { DataStatus } from "../../../../shared/model/market";
import type {
  TurnoverInsightPanelViewModel,
  TurnoverInsightViewState,
} from "./turnoverInsightTypes";

export interface IndexTurnoverInsightPanelViewModel extends TurnoverInsightPanelViewModel {
  tsCode: string;
  indexName: string;
}

export interface IndexTurnoverInsightViewModel {
  status: DataStatus;
  tradingDay: {
    expectedTradeDate: string;
    observedTradeDate: string | null;
    previousObservedTradeDate: string | null;
  };
  asOf: string | null;
  indices: readonly IndexTurnoverInsightPanelViewModel[];
  message: string | null;
  exceptionCode: string | null;
}

export type IndexTurnoverInsightCapabilityState = "loading" | "supported" | "unsupported";

export interface IndexTurnoverInsightControllerResult {
  capabilityState: IndexTurnoverInsightCapabilityState;
  viewState: TurnoverInsightViewState;
  model: IndexTurnoverInsightViewModel | null;
  errorMessage: string | null;
  retry: () => void;
}
