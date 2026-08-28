interface SectorAnalysisMethodBarProps {
  activeMethod: SectorAnalysisMethod;
  onSelect: (method: SectorAnalysisMethod) => void;
  onUnavailable: () => void;
}

export type SectorAnalysisMethod = "momentum-ranking" | "dual-momentum";

const availableMethods: ReadonlyArray<{ key: SectorAnalysisMethod; label: string }> = [
  { key: "momentum-ranking", label: "动量排名" },
  { key: "dual-momentum", label: "双动量" },
];
const unavailableMethods = ["相对轮动", "成员广度", "量价分布"] as const;

export function SectorAnalysisMethodBar({ activeMethod, onSelect, onUnavailable }: SectorAnalysisMethodBarProps) {
  return (
    <div className="sector-analysis-method-bar" role="tablist" aria-label="板块分析方法">
      {availableMethods.map((method) => (
        <button
          aria-pressed={activeMethod === method.key}
          className={activeMethod === method.key ? "active" : ""}
          key={method.key}
          role="tab"
          type="button"
          onClick={() => onSelect(method.key)}
        >
          {method.label}
        </button>
      ))}
      {unavailableMethods.map((label) => (
        <button aria-pressed="false" key={label} role="tab" type="button" onClick={onUnavailable}>
          {label}
        </button>
      ))}
    </div>
  );
}
