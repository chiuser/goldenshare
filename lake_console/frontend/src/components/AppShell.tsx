import { useState, type ReactNode } from "react";
import { Badge } from "./Badge";

export type ActivePage = "datasets" | "datasetDetail" | "commands" | "risks";

type AppShellProps = {
  activePage: ActivePage;
  children: ReactNode;
  initialized: boolean;
  onNavigate: (page: ActivePage) => void;
};

export function AppShell({ activePage, children, initialized, onNavigate }: AppShellProps) {
  return (
    <div className="app">
      <header className="app-header">
        <div className="app-brand">
          <LogoMark />
          <div>
            <strong>数据湖控制台</strong>
            <span>本地 Tushare Parquet 数据湖</span>
          </div>
        </div>
        <Badge tone={initialized ? "success" : "warning"}>
          {initialized ? "数据湖已初始化" : "等待初始化"}
        </Badge>
      </header>

      <div className="app-body">
        <aside className="sidebar">
          <div className="sidebar-section-label">本地数据湖</div>
          <button
            className={activePage === "datasets" || activePage === "datasetDetail" ? "sidebar-link active" : "sidebar-link"}
            onClick={() => onNavigate("datasets")}
            type="button"
          >
            数据集总览
          </button>
          <button className={activePage === "commands" ? "sidebar-link active" : "sidebar-link"} onClick={() => onNavigate("commands")} type="button">
            命令示例
          </button>
          <button className={activePage === "risks" ? "sidebar-link active" : "sidebar-link"} onClick={() => onNavigate("risks")} type="button">
            风险
          </button>
          <div className="sidebar-section-label">边界</div>
          <span className="sidebar-link static">不接远程 DB</span>
          <span className="sidebar-link static">不进生产部署</span>
        </aside>

        <main className="main">
          <section className="content">{children}</section>
        </main>
      </div>
    </div>
  );
}

function LogoMark() {
  const [logoAvailable, setLogoAvailable] = useState(true);
  if (logoAvailable) {
    return (
      <span className="logo-mark">
        <img alt="数据湖控制台" onError={() => setLogoAvailable(false)} src="/lake-console-logo.png" />
      </span>
    );
  }
  return <span className="logo-mark fallback">湖</span>;
}
