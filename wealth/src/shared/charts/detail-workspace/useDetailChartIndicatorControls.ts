import { useState } from "react";

import type { DetailChartIndicatorControls, DetailChartIndicatorPanelKey } from "./detailChartTypes";

export function useDetailChartIndicatorControls(tsCode: string): DetailChartIndicatorControls {
  const [selection, setSelection] = useState(() => ({
    tsCode,
    hiddenIndicatorPanels: new Set<DetailChartIndicatorPanelKey>(),
  }));

  if (selection.tsCode !== tsCode) {
    setSelection({ tsCode, hiddenIndicatorPanels: new Set() });
  }

  return {
    hiddenIndicatorPanels: selection.hiddenIndicatorPanels,
    onToggleIndicatorPanel(panel) {
      setSelection((current) => {
        const hiddenIndicatorPanels = new Set(current.hiddenIndicatorPanels);
        if (!hiddenIndicatorPanels.delete(panel)) hiddenIndicatorPanels.add(panel);
        return { ...current, hiddenIndicatorPanels };
      });
    },
  };
}
