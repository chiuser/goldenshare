const volumeNumber = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 2,
  useGrouping: false,
});

export function formatIndexVolumeLots(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  if (Math.abs(value) >= 100_000_000) return `${volumeNumber.format(value / 100_000_000)}亿手`;
  if (Math.abs(value) >= 10_000) return `${volumeNumber.format(value / 10_000)}万手`;
  return `${volumeNumber.format(value)}手`;
}
