import type { NineTurnLayerViewModel } from "../model/nineTurnTypes";
import "./nine-turn-layer-status.css";

export function NineTurnLayerStatus({
  droppedMarkerCount,
  layer,
  onRetry,
}: {
  droppedMarkerCount: number;
  layer: NineTurnLayerViewModel;
  onRetry: () => void;
}) {
  if (layer.phase === "IDLE" || (layer.phase === "READY" && droppedMarkerCount === 0)) return null;
  const alignmentMessage = droppedMarkerCount > 0
    ? `${droppedMarkerCount} 个九转标记未找到对应 K 线，已隐藏。`
    : null;
  return (
    <div className={`nine-turn-layer-status ${layer.phase.toLowerCase()}`} role="status">
      <span>{alignmentMessage ?? layer.message ?? fallbackMessage(layer.phase)}</span>
      {layer.canRetry ? (
        <button type="button" onClick={onRetry}>重试九转</button>
      ) : null}
    </div>
  );
}

function fallbackMessage(phase: NineTurnLayerViewModel["phase"]): string {
  if (phase === "EMPTY") return "当前窗口暂无九转标记。";
  if (phase === "SOURCE_EMPTY") return "九转数据尚未覆盖当前窗口。";
  if (phase === "PARTIAL") return "九转数据部分缺失，已展示可确认标记。";
  if (phase === "FORBIDDEN") return "当前账号无权查看九转序列。";
  if (phase === "UNSUPPORTED") return "当前周期不提供九转序列。";
  if (phase === "LOADING") return "正在加载九转序列。";
  return "九转序列加载失败。";
}
