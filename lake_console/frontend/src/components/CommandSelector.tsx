import type { ReactNode } from "react";
import { Badge } from "./Badge";
import type { CommandExampleGroup, CommandExampleItem } from "../types";

type CommandSelectorProps = {
  groups: CommandExampleGroup[];
  selectedGroup: CommandExampleGroup;
  selectedItem: CommandExampleItem | null;
  onSelectGroup: (groupKey: string) => void;
  onSelectItem: (itemKey: string) => void;
};

export function CommandSelector({
  groups,
  selectedGroup,
  selectedItem,
  onSelectGroup,
  onSelectItem,
}: CommandSelectorProps) {
  return (
    <>
      <div className="command-notice">
        <div>
          <strong>只读提示</strong>
          <span>本页只展示命令，不会执行写入。请在本地终端确认参数后执行。</span>
        </div>
        <div className="command-notice-tags">
          <Badge tone="brand">不执行命令</Badge>
          <Badge tone="brand">后端 Catalog</Badge>
          <Badge tone="muted">需人工确认参数</Badge>
        </div>
      </div>
      <div className="command-toolbar">
        <CommandSelectField label="展示分组">
          <select value={selectedGroup.group_key} onChange={(event) => onSelectGroup(event.target.value)}>
            {groups.map((group) => (
              <option key={group.group_key} value={group.group_key}>
                {group.group_label}
              </option>
            ))}
          </select>
        </CommandSelectField>
        <CommandSelectField label="数据集 / 命令集合">
          <select value={selectedItem?.item_key ?? ""} onChange={(event) => onSelectItem(event.target.value)}>
            {selectedGroup.items.map((item) => (
              <option key={item.item_key} value={item.item_key}>
                {item.display_name}
              </option>
            ))}
          </select>
        </CommandSelectField>
      </div>
    </>
  );
}

function CommandSelectField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="command-select-field">
      <span>{label}</span>
      {children}
    </label>
  );
}
