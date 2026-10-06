import { useState, type ReactNode } from "react";
import { buildIndexDetailPath, DEFAULT_WEALTH_PATH, navigateWealth, resolveTopMarketNavPath } from "../../app/routes/routerState";
import { PageBreadcrumb } from "../../shared/ui/page-breadcrumb/PageBreadcrumb";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import { useWealthExplorationShell } from "../wealth-exploration/layout/useWealthExplorationShell";
import "./data-center-page.css";
export function DataCenterShell({ announcement = false, children }: { announcement?: boolean; children: ReactNode }) {
  // Audited existing hook reads only the common market context/tickers, not exploration datasets.
  const { model } = useWealthExplorationShell(); const [toast, setToast] = useState("");
  return <div className="market-terminal dc-page"><TopMarketBar activeNav="data" tickers={model.tickers}
    onTickerSelect={code => navigateWealth(buildIndexDetailPath(code))} onNavigate={target => { const path = resolveTopMarketNavPath(target); if (path) navigateWealth(path); else setToast("该入口暂未开放"); }} />
    <main className="dc-shell"><PageBreadcrumb sessionStatus={model.pageContext?.sessionStatus ?? "CLOSED"} onNavigate={navigateWealth}
      items={[{ label: "财势乾坤", path: DEFAULT_WEALTH_PATH }, { label: "数据中心", path: "/wealth/data-center" }, ...(announcement ? [{ label: "上市公司公告" }] : [])]} />{children}</main>
    {toast && <button className="dc-toast" type="button" onClick={() => setToast("")}>{toast}</button>}
  </div>;
}
