import { CommandExampleItemDetail } from "./CommandExampleItemDetail";
import { CommandSelector } from "./CommandSelector";
import { EmptyState } from "./EmptyState";
import type { CommandExampleGroup } from "../types";

type CommandExamplesPanelProps = {
  error: string | null;
  groups: CommandExampleGroup[];
  selectedGroupKey: string;
  selectedItemKey: string;
  onSelectGroup: (groupKey: string) => void;
  onSelectItem: (itemKey: string) => void;
};

export function CommandExamplesPanel({
  error,
  groups,
  selectedGroupKey,
  selectedItemKey,
  onSelectGroup,
  onSelectItem,
}: CommandExamplesPanelProps) {
  if (error) {
    return <div className="alert error">命令示例加载失败：{error}</div>;
  }
  if (!groups.length) {
    return <EmptyState title="正在加载命令示例" description="命令来自后端 Lake catalog，前端不会自行拼接。" />;
  }

  const selectedGroup = groups.find((group) => group.group_key === selectedGroupKey) ?? groups[0];
  const selectedItem = selectedGroup.items.find((item) => item.item_key === selectedItemKey) ?? selectedGroup.items[0] ?? null;

  return (
    <div className="command-examples">
      <CommandSelector
        groups={groups}
        selectedGroup={selectedGroup}
        selectedItem={selectedItem}
        onSelectGroup={onSelectGroup}
        onSelectItem={onSelectItem}
      />
      {selectedItem ? <CommandExampleItemDetail item={selectedItem} /> : <EmptyState title="暂无命令示例" description="当前分组没有可展示命令。" />}
    </div>
  );
}
