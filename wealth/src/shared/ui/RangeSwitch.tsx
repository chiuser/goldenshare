interface RangeSwitchProps {
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
  ariaLabel: string;
}

export function RangeSwitch({ value, options, onChange, ariaLabel }: RangeSwitchProps) {
  return (
    <div className="range-switch" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          className={option.value === value ? "active" : ""}
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
