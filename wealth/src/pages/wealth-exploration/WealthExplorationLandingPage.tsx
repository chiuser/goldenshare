import { WealthExplorationShell } from "./layout/WealthExplorationShell";
import "./wealth-exploration-page.css";

interface WealthExplorationLandingPageProps {
  search?: string;
}

export function WealthExplorationLandingPage({ search }: WealthExplorationLandingPageProps) {
  return <WealthExplorationShell activeShortcutKey={null} search={search} />;
}
