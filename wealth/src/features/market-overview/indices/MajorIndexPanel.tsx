import { Panel } from "../../../shared/ui/Panel";
import { directionClass } from "../../../shared/lib/marketDirection";
import { formatPoint, formatSignedPercent } from "../../../shared/lib/formatters";
import type { QuoteItem } from "../api/marketOverviewTypes";

interface MajorIndexPanelProps {
  indices: QuoteItem[];
  onAction: (message: string) => void;
}

export function MajorIndexPanel({ indices, onAction }: MajorIndexPanelProps) {
  return (
    <Panel
      title="主要指数"
      help="展示 A 股核心指数的最新点位、涨跌额和涨跌幅；点位、涨跌额、涨跌幅均严格红涨绿跌。点击指数卡进入指数详情。"
      meta={<span className="secondary">2 行 × 5 个；点击进入指数详情</span>}
    >
      <div className="index-grid">
        {indices.map((index, indexNumber) => (
          <button
            className={indexNumber === 0 ? "index-card selected" : "index-card"}
            key={index.code}
            type="button"
            onClick={() => onAction(`进入详情：${index.code}`)}
          >
            <span className="index-name">
              <span>{index.name}</span>
              <span className="num muted">{index.code}</span>
            </span>
            <strong className={`index-point num ${directionClass(index.direction)}`}>{formatPoint(index.point)}</strong>
            <span className={`index-change num ${directionClass(index.direction)}`}>
              <span>
                {index.change > 0 ? "+" : ""}
                {index.change.toFixed(2)}
              </span>
              <span>{formatSignedPercent(index.pct)}</span>
            </span>
          </button>
        ))}
      </div>
    </Panel>
  );
}
