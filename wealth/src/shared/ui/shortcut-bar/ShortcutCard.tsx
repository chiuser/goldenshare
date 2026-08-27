import type { ShortcutItem } from "./shortcutBarTypes";

interface ShortcutCardProps {
  item: ShortcutItem;
  selected: boolean;
  disabled?: boolean;
  onSelect: (item: ShortcutItem) => void;
}

export function ShortcutCard({ item, selected, disabled = false, onSelect }: ShortcutCardProps) {
  const isDisabled = disabled || item.disabled === true;
  return (
    <button
      className={selected ? "shortcut-card selected" : "shortcut-card"}
      disabled={isDisabled}
      type="button"
      onClick={() => onSelect(item)}
    >
      <div className="shortcut-top">
        <span className="shortcut-title">{item.title}</span>
        {item.badge ? (
          <span className={item.badgeTone === "alert" ? "badge" : "badge neutral"}>{item.badge}</span>
        ) : null}
      </div>
      <div className="shortcut-desc">{item.description}</div>
    </button>
  );
}
