import type { NineTurnPeriod } from "../../nine-turn/api/nineTurnApiTypes";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";

export const INDEX_TECHNICAL_NINE_TURN_PERIODS = [
  { label: "日线", period: "day" },
  { label: "15分钟", period: "15" },
  { label: "30分钟", period: "30" },
  { label: "60分钟", period: "60" },
  { label: "90分钟", period: "90" },
  { label: "120分钟", period: "120" },
] as const satisfies ReadonlyArray<{ label: string; period: NineTurnPeriod }>;

export type IndexTechnicalNineTurnPeriod = typeof INDEX_TECHNICAL_NINE_TURN_PERIODS[number]["period"];

export type IndexTechnicalNineTurnSummary = Record<IndexTechnicalNineTurnPeriod, NineTurnLayerViewModel>;
