import { Badge } from "./Badge";
import { CopyButton } from "./CopyButton";
import type { CommandExample } from "../types";

type CommandExampleCardProps = {
  example: CommandExample;
};

export function CommandExampleCard({ example }: CommandExampleCardProps) {
  return (
    <article className="command-card">
      <div className="command-card-header">
        <div>
          <strong>{example.title}</strong>
          <span>{example.description}</span>
        </div>
        <Badge tone="brand">{scenarioLabel(example.scenario)}</Badge>
      </div>
      <div className="command-code-row">
        <code>{example.command}</code>
        <CopyButton value={example.command} />
      </div>
      {example.prerequisites.length || example.notes.length ? (
        <div className="command-meta">
          {example.prerequisites.length ? <CommandMetaBlock title="前置条件" items={example.prerequisites} /> : null}
          {example.notes.length ? <CommandMetaBlock title="备注" items={example.notes} /> : null}
        </div>
      ) : null}
    </article>
  );
}

function CommandMetaBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="command-meta-block">
      <span>{title}</span>
      <p>{items.join("；")}</p>
    </div>
  );
}

function scenarioLabel(scenario: string): string {
  const labels: Record<string, string> = {
    init: "初始化",
    status: "状态",
    plan: "预览",
    sync_point: "单点同步",
    sync_range: "区间同步",
    sync_snapshot: "快照刷新",
    derive: "派生",
    research: "Research",
    maintenance: "维护",
    diagnostic: "诊断",
  };
  return labels[scenario] ?? scenario;
}
