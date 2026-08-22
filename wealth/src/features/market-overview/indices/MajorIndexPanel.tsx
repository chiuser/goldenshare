import { Panel } from "../../../shared/ui/Panel";
import { directionClass } from "../../../shared/lib/marketDirection";
import { formatPoint, formatSignedPercent } from "../../../shared/lib/formatters";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { MajorIndexViewItem } from "../../major-indices/api/marketMajorIndicesAdapter";

interface MajorIndexPanelProps {
  viewState: "loading" | "ready" | "error";
  indices?: MajorIndexViewItem[];
  errorMessage?: string;
  onIndexSelect: (tsCode: string) => void;
}

export function MajorIndexPanel({ viewState, indices, errorMessage, onIndexSelect }: MajorIndexPanelProps) {
  const rows = indices ?? [];

  return (
    <Panel
      title="主要指数"
      help="展示 A 股核心指数的最新点位、涨跌额和涨跌幅；点位、涨跌额、涨跌幅均严格红涨绿跌。点击指数卡进入指数详情。"
    >
      {viewState === "loading" ? (
        <div className="summary-state-wrap">
          <SkeletonBlock />
        </div>
      ) : null}
      {viewState === "error" ? (
        <div className="summary-state-wrap">
          <div className="state-block error-box">
            <strong>error</strong>
            <br />
            <span>{errorMessage ?? "请求超时，请稍后重试。"}</span>
          </div>
        </div>
      ) : null}
      {viewState === "ready" ? (
        <div className="index-grid">
          {rows.map((index, indexNumber) => (
            <button
              className={indexNumber === 0 ? "index-card selected" : "index-card"}
              key={index.code}
              type="button"
              onClick={() => onIndexSelect(index.code)}
            >
              <span className="index-name">
                <span>{index.name}</span>
                <span className="num muted">{index.code}</span>
              </span>
              <strong className={`index-point num ${directionClass(index.direction)}`}>{renderPoint(index.point)}</strong>
              <span className={`index-change num ${directionClass(index.direction)}`}>
                <span>{renderChange(index.change)}</span>
                <span>{renderChangePct(index.pct)}</span>
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

function renderPoint(value: number | null): string {
  if (value === null) return "--";
  return formatPoint(value);
}

function renderChange(value: number | null): string {
  if (value === null) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function renderChangePct(value: number | null): string {
  if (value === null) return "--";
  return formatSignedPercent(value);
}
