type DetailItemProps = {
  label: string;
  value: string;
  wide?: boolean;
};

export function DetailItem({ label, value, wide = false }: DetailItemProps) {
  return (
    <div className={wide ? "detail-item wide" : "detail-item"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
