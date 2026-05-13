import type { NodeSummary } from "../types";
import { formatBytes, formatDateTime, formatNodeDateOrMonthRange, formatRowCount } from "../utils/format";
import { Badge } from "./Badge";
import { CopyButton } from "./CopyButton";

type NodeRowProps = {
  node: NodeSummary;
};

export function NodeRow({ node }: NodeRowProps) {
  return (
    <article className="layer-row surface-card">
      <div className="layer-row-header">
        <div className="layer-mark" aria-hidden="true">
          {node.layer.slice(0, 1).toUpperCase()}
        </div>
        <div className="layer-heading">
          <strong>{node.node_name}</strong>
          <span>
            {node.layer_name} / {node.node_key}
          </span>
          <div className="layer-chip-row">
            <Badge tone="brand">{node.asset_role_label}</Badge>
            <Badge tone="muted">{node.scan_profile}</Badge>
            {node.freqs.map((freq) => (
              <Badge tone="muted" key={`${node.node_key}-${freq}`}>
                {freq}m
              </Badge>
            ))}
          </div>
        </div>
      </div>
      <div className="layer-row-body">
        <p>{node.recommended_usage}</p>
        <p>{node.source_node_keys.length ? `来源节点：${node.source_node_keys.join(", ")}` : "来源节点：-"}</p>
      </div>
      <NodePath path={node.path} />
      <dl className="layer-stats">
        <NodeStat label="分区" value={String(node.partition_count)} />
        <NodeStat label="文件" value={String(node.file_count)} />
        <NodeStat label="大小" value={formatBytes(node.total_bytes)} />
        {node.row_count !== null ? <NodeStat label="行数" value={formatRowCount(node.row_count)} /> : null}
        <NodeStat label="日期/月" value={formatNodeDateOrMonthRange(node)} />
        <NodeStat label="最近更新" value={formatDateTime(node.latest_modified_at)} />
      </dl>
    </article>
  );
}

function NodePath({ path }: { path: string }) {
  return (
    <div className="layer-path">
      <span>文件路径</span>
      <div className="layer-path-row">
        <code>{path}</code>
        <CopyButton className="layer-path-copy" idleLabel="复制路径" value={path} />
      </div>
    </div>
  );
}

function NodeStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
