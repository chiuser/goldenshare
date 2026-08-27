interface SectorAnalysisMethodBarProps {
  onUnavailable: () => void;
}

const unavailableMethods = ["双动量", "相对轮动", "成员广度", "量价分布"] as const;

export function SectorAnalysisMethodBar({ onUnavailable }: SectorAnalysisMethodBarProps) {
  return (
    <div className="sector-analysis-method-bar" role="tablist" aria-label="板块分析方法">
      <button aria-pressed="true" className="active" role="tab" type="button">动量排名</button>
      {unavailableMethods.map((label) => (
        <button aria-pressed="false" key={label} role="tab" type="button" onClick={onUnavailable}>
          {label}
        </button>
      ))}
    </div>
  );
}
