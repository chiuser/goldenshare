import { SectorAnalysisMethodBar } from "../../features/wealth-exploration/sector-analysis/navigation/SectorAnalysisMethodBar";
import { WealthExplorationShell } from "./layout/WealthExplorationShell";
import "./wealth-exploration-page.css";

interface SectorAnalysisPageProps {
  search?: string;
}

export function SectorAnalysisPage({ search }: SectorAnalysisPageProps) {
  return (
    <WealthExplorationShell activeShortcutKey="sector-analysis" currentPageLabel="板块分析" search={search}>
      {({ showToast }) => <SectorAnalysisMethodBar onUnavailable={() => showToast("待建设")} />}
    </WealthExplorationShell>
  );
}
