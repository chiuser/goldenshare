import { ShortcutBar } from "../../../shared/ui/shortcut-bar/ShortcutBar";
import {
  getExplorationShortcutItems,
  type ExplorationShortcutKey,
} from "./explorationNavigation";

interface ExplorationShortcutBarProps {
  activeKey: ExplorationShortcutKey | null;
  onNavigate: (path: string) => void;
}

export function ExplorationShortcutBar({ activeKey, onNavigate }: ExplorationShortcutBarProps) {
  return <ShortcutBar activeKey={activeKey} items={getExplorationShortcutItems()} onNavigate={onNavigate} />;
}
