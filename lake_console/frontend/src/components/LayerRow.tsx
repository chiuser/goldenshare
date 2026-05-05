import type { LayerSummary } from "../types";
import { formatBytes, formatDateTime, formatLayerDateOrMonthRange, formatRowCount } from "../utils/format";
import { humanizeLayerPurpose, humanizeLayerUsage, layerDisplayName, layerInitial } from "../utils/layerPresentation";
import { Badge } from "./Badge";
import { CopyButton } from "./CopyButton";

type LayerRowProps = {
  layer: LayerSummary;
};

export function LayerRow({ layer }: LayerRowProps) {
  return (
    <article className="layer-row surface-card">
      <div className="layer-row-header">
        <div className="layer-mark" aria-hidden="true">
          {layerInitial(layer)}
        </div>
        <div className="layer-heading">
          <strong>{layerDisplayName(layer)}</strong>
          <span>{layer.layer}</span>
          <div className="layer-chip-row">
            <Badge tone="brand">{layer.layout}</Badge>
            {layer.freqs.map((freq) => (
              <Badge tone="muted" key={`${layer.layer}-${layer.layout}-${freq}`}>
                {freq}m
              </Badge>
            ))}
          </div>
        </div>
      </div>
      <div className="layer-row-body">
        <p>{humanizeLayerPurpose(layer)}</p>
        <p>{humanizeLayerUsage(layer)}</p>
      </div>
      <LayerPath path={layer.path} />
      <dl className="layer-stats">
        <LayerStat label="分区" value={String(layer.partition_count)} />
        <LayerStat label="文件" value={String(layer.file_count)} />
        <LayerStat label="大小" value={formatBytes(layer.total_bytes)} />
        {layer.row_count !== null ? <LayerStat label="行数" value={formatRowCount(layer.row_count)} /> : null}
        <LayerStat label="日期/月" value={formatLayerDateOrMonthRange(layer)} />
        <LayerStat label="最近更新" value={formatDateTime(layer.latest_modified_at)} />
      </dl>
    </article>
  );
}

function LayerPath({ path }: { path: string }) {
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

function LayerStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
