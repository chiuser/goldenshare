type DetailItemProps = {
  label: string;
  value: string;
  wide?: boolean;
};

export function DetailItem({ label, value, wide = false }: DetailItemProps) {
  const classes = ["detail-item", "surface-card", wide ? "wide" : ""].filter(Boolean).join(" ");
  return (
    <div className={classes}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
