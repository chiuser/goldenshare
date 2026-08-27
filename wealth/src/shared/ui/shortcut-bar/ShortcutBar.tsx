import { ShortcutCard } from "./ShortcutCard";
import type { ShortcutItem } from "./shortcutBarTypes";
import "./shortcut-bar.css";

interface ShortcutBarProps {
  items: readonly ShortcutItem[];
  activeKey: string | null;
  onNavigate: (path: string) => void;
}

export function ShortcutBar({ items, activeKey, onNavigate }: ShortcutBarProps) {
  return (
    <section className="shortcut-bar" aria-label="ShortcutBar / 页面内快捷入口">
      {items.map((item) => (
        <ShortcutCard
          disabled={item.disabled}
          item={item}
          key={item.key}
          selected={activeKey === item.key}
          onSelect={(selectedItem) => onNavigate(selectedItem.path)}
        />
      ))}
    </section>
  );
}
