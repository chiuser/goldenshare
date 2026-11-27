import { useMajorEtfMonitor } from "../model/useMajorEtfMonitor";
import { MajorEtfQuotes } from "./MajorEtfQuotes";
import { MajorEtfTurnoverChart } from "./MajorEtfTurnoverChart";
import "./major-etf-monitor.css";

export function MajorEtfMonitor() {
  const { state, retry } = useMajorEtfMonitor();
  return (
    <div className="etf-activity-workspace major-etf-monitor">
      <MajorEtfTurnoverChart state={state} />
      <MajorEtfQuotes state={state} onRetry={retry} />
    </div>
  );
}
