import { useEffect, useState } from "react";
import { positionsReadApi } from "../api/positionsApi";
import type { PositionsResponse } from "../api/generatedContracts";
import { PositionsReader } from "./positionsReader";

export function usePositions(selected: string | null, revision: number) {
  const [read, setRead] = useState<{ selected: string; revision: number; data: PositionsResponse | null; error: boolean } | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!selected) return;
    setRead({ selected, revision, data: null, error: false });
    const reader = new PositionsReader(selected, positionsReadApi, event => setRead(previous => ({
      selected, revision, data: event.kind === "data" ? event.data : previous?.data ?? null, error: event.kind === "error" })));
    const visibility = () => { if (document.visibilityState === "hidden") reader.stop(); else reader.start(); };
    visibility();
    document.addEventListener("visibilitychange", visibility);
    return () => { document.removeEventListener("visibilitychange", visibility); reader.stop(); };
  }, [selected, revision, reload]);
  const current = read?.selected === selected && read.revision === revision ? read : null;
  return { data: current?.data ?? null, error: current?.error ?? false,
    loading: !!selected && !current?.data && !current?.error, refresh: () => setReload(value => value + 1) };
}
