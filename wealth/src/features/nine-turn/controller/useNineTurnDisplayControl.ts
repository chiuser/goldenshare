import { useState } from "react";

export interface NineTurnDisplayControl {
  available: boolean;
  visible: boolean;
  onToggle: () => void;
}

export function useNineTurnDisplayControl(tsCode: string, available: boolean): NineTurnDisplayControl {
  const [selection, setSelection] = useState(() => ({ tsCode, selected: true }));
  const changed = selection.tsCode !== tsCode;
  if (changed) {
    setSelection({ tsCode, selected: true });
  }

  return {
    available,
    visible: available && (changed || selection.selected),
    onToggle: () => setSelection(current => ({ tsCode, selected: !current.selected })),
  };
}
