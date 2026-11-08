import { useEffect, useRef, useState } from "react";

import type { DetailChartIndicatorControls, DetailChartIndicatorPanelKey } from "./detailChartTypes";

const DEFAULT_INDICATORS = ["volume", "macd", "kdj"] as const;
const ALL_INDICATORS = [...DEFAULT_INDICATORS, "quantitativeStructure"] as const;
const MAX_VISIBLE_INDICATORS = 3;

function initialSelection(tsCode: string) {
  return {
    tsCode,
    selected: new Set<DetailChartIndicatorPanelKey>(DEFAULT_INDICATORS),
    rejectedClick: null as symbol | null,
  };
}

export function useDetailChartIndicatorControls(
  tsCode: string,
  quantitativeStructureAvailable = false,
  onLimitReached?: () => void,
): DetailChartIndicatorControls {
  const [selection, setSelection] = useState(() => initialSelection(tsCode));
  const lastNotifiedClick = useRef<symbol | null>(null);

  if (selection.tsCode !== tsCode) {
    setSelection(initialSelection(tsCode));
  }

  const { rejectedClick, selected } = selection;
  useEffect(() => {
    if (rejectedClick === null || rejectedClick === lastNotifiedClick.current) return;
    lastNotifiedClick.current = rejectedClick;
    onLimitReached?.();
  }, [onLimitReached, rejectedClick]);

  return {
    hiddenIndicatorPanels: new Set(ALL_INDICATORS.filter(panel =>
      !selected.has(panel) || (panel === "quantitativeStructure" && !quantitativeStructureAvailable))),
    quantitativeStructureAvailable,
    onToggleIndicatorPanel(panel) {
      if (panel === "quantitativeStructure" && !quantitativeStructureAvailable) return;
      const click = Symbol();
      setSelection((current) => {
        const next = new Set(current.selected);
        if (next.delete(panel)) return { ...current, selected: next };

        const structureHidden = !quantitativeStructureAvailable && next.has("quantitativeStructure");
        const visibleCount = next.size - Number(structureHidden);
        if (visibleCount >= MAX_VISIBLE_INDICATORS) return { ...current, rejectedClick: click };

        next.add(panel);
        if (structureHidden && visibleCount + 1 === MAX_VISIBLE_INDICATORS) next.delete("quantitativeStructure");
        return { ...current, selected: next };
      });
    },
  };
}
