interface ShortcutBarProps {
  onAction: (message: string) => void;
}

const entries = [
  ["市场温度与情绪", "新", "进入分析页查看温度、情绪、资金与风险，不在本页展示分数。", "/market/emotion", true],
  ["机会雷达", "3", "查看板块轮动、资金回流与机会线索。", "/opportunity/radar", false],
  ["我的自选", "18", "查看自选股行情、分组与提醒状态。", "/watchlist", false],
  ["我的持仓", "5", "查看手工登记持仓和当日波动。", "/positions", false],
  ["提醒中心", "2", "管理价格、资金、技术和计划提醒。", "/alerts", false],
  ["用户设置", "--", "管理账户、偏好和展示设置。", "/settings", false],
] as const;

export function ShortcutBar({ onAction }: ShortcutBarProps) {
  return (
    <section className="shortcut-bar" aria-label="ShortcutBar / 页面内快捷入口">
      {entries.map(([title, badge, desc, route, selected]) => (
        <article
          className={selected ? "shortcut-card selected" : "shortcut-card"}
          key={route}
          onClick={() => onAction(`跳转：${route}`)}
        >
          <div className="shortcut-top">
            <span className="shortcut-title">{title}</span>
            <span className={badge === "3" || badge === "2" ? "badge" : "badge neutral"}>{badge}</span>
          </div>
          <div className="shortcut-desc">{desc}</div>
        </article>
      ))}
    </section>
  );
}
