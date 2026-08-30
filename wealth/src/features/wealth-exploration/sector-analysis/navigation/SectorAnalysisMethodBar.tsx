interface SectorAnalysisMethodBarProps {
  activeMethod: SectorAnalysisMethod;
  onSelect: (method: SectorAnalysisMethod) => void;
}

export type SectorAnalysisMethod = "momentum-ranking" | "dual-momentum" | "relative-rotation" | "member-breadth" | "price-volume";

const availableMethods: ReadonlyArray<{ key: SectorAnalysisMethod; label: string }> = [
  { key: "momentum-ranking", label: "动量排名" },
  { key: "dual-momentum", label: "双动量" },
  { key: "relative-rotation", label: "相对轮动" },
  { key: "member-breadth", label: "成员广度" },
  { key: "price-volume", label: "量价分布" },
];

export function SectorAnalysisMethodBar({ activeMethod, onSelect }: SectorAnalysisMethodBarProps) {
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
    </div>
  );
}
