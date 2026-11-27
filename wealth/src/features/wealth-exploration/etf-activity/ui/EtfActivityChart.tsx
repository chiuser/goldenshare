import type { EtfActivityTrendPoint } from "../api/etfActivityApi";
import { EtfTurnoverPlot } from "./EtfTurnoverPlot";

const SERIES = [
  { field: "amountYuan", label: "成交额", color: "amount" },
  { field: "ma5Yuan", label: "MA5", color: "ma5" },
  { field: "ma20Yuan", label: "MA20", color: "ma20" },
] as const;

interface EtfActivityChartProps {
  points: EtfActivityTrendPoint[];
  selectedDate: string | null;
  onSelectDate: (date: string) => void;
}

export function EtfActivityChart(props: EtfActivityChartProps) {
  return <EtfTurnoverPlot {...props} series={SERIES} turnoverUnit=" 亿"
    ariaLabel="ETF 日成交额趋势图，使用左右方向键选择交易日" />;
}
