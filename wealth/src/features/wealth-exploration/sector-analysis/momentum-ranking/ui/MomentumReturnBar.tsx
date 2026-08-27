interface MomentumReturnBarProps {
  value: number | null;
  widthPct: number;
  label: string;
}

export function MomentumReturnBar({ value, widthPct, label }: MomentumReturnBarProps) {
  if (value === null) return <span className="momentum-missing-value num">--</span>;
  const positive = value >= 0;
  return (
    <span className="momentum-return-bar" aria-label={label}>
      <span className="momentum-return-zero" aria-hidden="true" />
      <span
        aria-hidden="true"
        className={positive ? "momentum-return-fill up-fill" : "momentum-return-fill down-fill"}
        style={positive ? { left: "50%", width: `${widthPct}%` } : { left: `${50 - widthPct}%`, width: `${widthPct}%` }}
      />
      <span className={`momentum-return-value num ${value > 0 ? "up" : value < 0 ? "down" : "flat"}`}>
        {label}
      </span>
    </span>
  );
}
