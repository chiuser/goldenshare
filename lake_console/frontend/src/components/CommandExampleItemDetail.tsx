import { Badge } from "./Badge";
import { CommandExampleCard } from "./CommandExampleCard";
import type { CommandExampleItem } from "../types";

type CommandExampleItemDetailProps = {
  item: CommandExampleItem;
};

export function CommandExampleItemDetail({ item }: CommandExampleItemDetailProps) {
  return (
    <div className="command-item-detail">
      <div className="command-item-title">
        <div>
          <strong>{item.display_name}</strong>
          <span>{item.item_key}</span>
        </div>
        <div className="command-item-badges">
          <Badge tone="brand">{item.item_type === "dataset" ? "数据集" : "命令集合"}</Badge>
          <Badge tone="muted">{item.examples.length} 条命令</Badge>
        </div>
      </div>
      {item.description ? <p>{item.description}</p> : null}
      <div className="command-card-list">
        {item.examples.map((example) => (
          <CommandExampleCard example={example} key={example.example_key} />
        ))}
      </div>
    </div>
  );
}
