import { CommandExamplesPanel } from "../components/CommandExamplesPanel";
import { PageHeader } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import type { CommandExampleGroup } from "../types";

type CommandExamplesPageProps = {
  commandError: string | null;
  commandGroups: CommandExampleGroup[];
  selectedCommandGroupKey: string;
  selectedCommandItemKey: string;
  onSelectGroup: (groupKey: string) => void;
  onSelectItem: (itemKey: string) => void;
};

export function CommandExamplesPage({
  commandError,
  commandGroups,
  selectedCommandGroupKey,
  selectedCommandItemKey,
  onSelectGroup,
  onSelectItem,
}: CommandExamplesPageProps) {
  return (
    <>
      <PageHeader
        eyebrow="Command guide"
        title="命令示例"
        description="按分组和数据集查看可执行 CLI 模板。页面只展示命令，不触发写入。"
        helpTitle="命令来自后端 Lake catalog，前端不自行拼接；真实写入继续在本地终端执行。"
      />
      <Panel title="操作提示" description="选择分组和数据集后，复制需要的命令到本地终端执行。">
        <CommandExamplesPanel
          error={commandError}
          groups={commandGroups}
          selectedGroupKey={selectedCommandGroupKey}
          selectedItemKey={selectedCommandItemKey}
          onSelectGroup={onSelectGroup}
          onSelectItem={onSelectItem}
        />
      </Panel>
    </>
  );
}
