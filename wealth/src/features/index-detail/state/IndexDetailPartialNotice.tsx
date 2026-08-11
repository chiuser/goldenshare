interface IndexDetailPartialNoticeProps {
  expectedTradeDate?: string;
  observedTradeDate?: string | null;
  reasons?: string[];
  variant: "partial" | "delayed";
}

export function IndexDetailPartialNotice({ expectedTradeDate, observedTradeDate, reasons = [], variant }: IndexDetailPartialNoticeProps) {
  const isPartial = variant === "partial";
  return (
    <section aria-label={isPartial ? "部分数据缺失" : "数据更新延迟"} className={`index-data-notice ${variant}`}>
      <div><i aria-hidden="true" /><strong>{isPartial ? "部分数据缺失" : "数据更新延迟"}</strong></div>
      <p>{isPartial ? partialCopy(reasons) : `数据更新至 ${observedTradeDate ?? "--"}，预期交易日为 ${expectedTradeDate ?? "--"}。`}</p>
    </section>
  );
}

function partialCopy(reasons: string[]): string {
  if (reasons.length === 0) return "部分行情暂不可用，其余行情与图表继续展示。";
  const visible = reasons.slice(0, 4);
  const suffix = reasons.length > visible.length ? `等 ${reasons.length} 项` : "";
  return `${visible.join("、")}${suffix}暂不可用，其余行情与图表继续展示。`;
}
