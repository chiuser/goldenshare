import type { ReactNode } from "react";
import { useIndexXxmLayer, type XxmLayerInput } from "./useIndexXxmLayer";
import { useXxmValuesAt, XxmSignalDetails } from "./XxmLayerUi";

export type XxmLayerView = ReturnType<typeof useIndexXxmLayer> & {
  valuesAt: ReturnType<typeof useXxmValuesAt>;
  renderDetails: (time: string) => ReactNode;
};
export type XxmLayerProps = XxmLayerInput & { children: (view: XxmLayerView) => ReactNode };

export function IndexXxmLayer({ children, ...input }: XxmLayerProps) {
  const layer = useIndexXxmLayer(input);
  const valuesAt = useXxmValuesAt(layer.data);
  return children({ ...layer, valuesAt, renderDetails: time => <XxmSignalDetails layer={layer} time={time} /> });
}
