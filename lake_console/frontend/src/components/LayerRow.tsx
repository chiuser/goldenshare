import type { LayerSummary } from "../types";
import { formatBytes, formatDateTime, formatLayerDateOrMonthRange, formatRowCount } from "../utils/format";
import { humanizeLayerPurpose, humanizeLayerUsage, layerDisplayName, layerInitial } from "../utils/layerPresentation";

type LayerRowProps = {
  layer: LayerSummary;
};

export function LayerRow({ layer }: LayerRowProps) {
  return (
    <article className="layer-row">
      <div className="layer-row-header">
        <div className="layer-mark" aria-hidden="true">
          {layerInitial(layer)}
        </div>
        <div>
          <strong>{layerDisplayName(layer)}</strong>
          <span>{layer.layer} · {layer.layout}</span>
        </div>
      </div>
      <div className="layer-row-body">
        <div>
          <p>{humanizeLayerPurpose(layer)}</p>
          <p>{humanizeLayerUsage(layer)}</p>
        </div>
        <code>{layer.path}</code>
      </div>
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

function LayerStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
