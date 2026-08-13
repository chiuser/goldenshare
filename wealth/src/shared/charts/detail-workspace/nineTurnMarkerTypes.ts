import type { Time } from "lightweight-charts";

export type NineTurnRenderDirection = "UP" | "DOWN";
export type NineTurnRenderSequence = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;

export interface NineTurnRenderMarker {
  anchorPrice: number;
  direction: NineTurnRenderDirection;
  sequenceNumber: NineTurnRenderSequence;
  time: Time;
}
