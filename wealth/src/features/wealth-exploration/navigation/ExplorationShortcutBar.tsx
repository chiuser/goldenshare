import { ShortcutBar } from "../../../shared/ui/shortcut-bar/ShortcutBar";
import {
  explorationShortcutItems,
  type ExplorationShortcutKey,
} from "./explorationNavigation";

interface ExplorationShortcutBarProps {
  activeKey: ExplorationShortcutKey | null;
  onNavigate: (path: string) => void;
}

export function ExplorationShortcutBar({ activeKey, onNavigate }: ExplorationShortcutBarProps) {
  return <ShortcutBar activeKey={activeKey} items={explorationShortcutItems} onNavigate={onNavigate} />;
}
