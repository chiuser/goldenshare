import { useMemo, useState } from "react";
import { Panel } from "../../../shared/ui/Panel";
import type { LadderV5PromotionLayer, LadderV5Stock, MarketOverview } from "../api/marketOverviewTypes";

interface StreakLadderPanelProps {
  overview: MarketOverview;
  onAction: (message: string) => void;
}

export function StreakLadderPanel({ overview, onAction }: StreakLadderPanelProps) {
  const [expandedLayers, setExpandedLayers] = useState<Set<string>>(new Set());
  const ladder = overview.ladderV5;

  const layers = useMemo(() => {
    if (!ladder) return [];

    const next: Array<
      | { type: "above"; key: string; stocks: LadderV5Stock[] }
      | { type: "first"; key: string; stocks: LadderV5Stock[] }
      | ({ type: "promotion"; key: string } & LadderV5PromotionLayer)
    > = [];

    if (ladder.highestStreakLevel >= 6) {
      next.push({ type: "above", key: "aboveFive", stocks: ladder.aboveFive });
    }

    const maxNormal = Math.min(ladder.highestStreakLevel, 5);
    for (let level = maxNormal; level >= 2; level -= 1) {
      const promotion = ladder.promotions[level];
      if (promotion) next.push({ type: "promotion", key: `promotion-${level}`, ...promotion });
    }

    if (ladder.highestStreakLevel >= 1) {
      next.push({ type: "first", key: "first", stocks: ladder.firstBoard });
    }
    return next;
  }, [ladder]);

  const totalStocks = useMemo(
    () =>
      layers.reduce(
        (sum, layer) =>
          sum +
          (layer.type === "promotion"
            ? layer.previousStocks.length + layer.currentStocks.length
            : layer.stocks.length),
        0,
      ),
    [layers],
  );

  const toggleLayer = (key: string) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const clsBy = (value: number) => {
    if (value > 0) return "up";
    if (value < 0) return "down";
    return "flat";
  };

  const fmtPct = (value: number) => (value >= 0 ? `+${value.toFixed(2)}%` : `${value.toFixed(2)}%`);

  const renderCard = (stock: LadderV5Stock, mode: "above" | "normal") => {
    const pctClass = clsBy(stock.changePct);
    const meta = mode === "above" ? `${stock.currentStreakLevel}板` : `开板 ${stock.openTimes}次`;
    const advClass = mode === "above" ? "above" : stock.advanced ? "advanced" : "not-advanced";
    return (
      <article
        className={`stock-compact-card-v5 ${advClass}`}
        key={`${stock.stockCode}-${stock.currentStreakLevel}`}
        title={`点击进入个股详情：${stock.stockName}｜${stock.stockCode}`}
        onClick={() => onAction(`进入个股详情：${stock.stockCode}`)}
      >
        <span className="stock-card-name-v5">{stock.stockName}</span>
        <span className="stock-card-code-v5">{stock.stockCode}</span>
        <span className={`stock-card-price-v5 num ${pctClass}`}>{stock.latestPrice.toFixed(2)}</span>
        <span className={`stock-card-change-v5 num ${pctClass}`}>{fmtPct(stock.changePct)}</span>
        <span className="stock-card-sector-v5">{stock.sectorName}</span>
        <span className="stock-card-meta-v5">{meta}</span>
      </article>
    );
  };

  const renderSide = (title: string, stocks: LadderV5Stock[]) => (
    <div className="ladder-side-v5">
      <div className="ladder-side-head-v5">
        <span>{title}</span>
        <span className="side-count">{stocks.length}只</span>
      </div>
      <div className="stock-grid-v5">
        {stocks.length ? stocks.map((stock) => renderCard(stock, "normal")) : <div className="ladder-empty-v5">暂无股票</div>}
      </div>
    </div>
  );

  return (
    <Panel
      title="连板天梯"
      help="Review v5：动态展示昨日层级到今日晋级层级；昨日层级展示全量昨日股票，今日层级只展示晋级成功股票；每层默认最多12只，可展开收起。"
      meta={<span className="secondary">昨日层级 → 今日晋级层级｜股票卡片可点击</span>}
    >
      <div className="limit-ladder-v5">
        {ladder ? (
          <>
            <div className="ladder-v5-summary">
              <div>
                <strong>{ladder.tradeDate} 连板天梯</strong>
                <span className="secondary">　最高 {ladder.highestStreakLevel} 板，昨日层级展示全量昨日股票，今日层级仅展示晋级成功股票。</span>
              </div>
              <div className="ladder-v5-tags">
                <span className="ladder-v5-tag">股票 {totalStocks} 项展示</span>
                <span className="ladder-v5-tag">每层默认最多 12 只</span>
              </div>
            </div>
            {layers.map((layer) => {
              const expanded = expandedLayers.has(layer.key);
              if (layer.type === "above" || layer.type === "first") {
                const isAbove = layer.type === "above";
                const needExpand = layer.stocks.length > 12;
                const label = isAbove ? "五板以上" : "首板";
                const subtitle = isAbove ? "只展示今日六板及以上，右下显示具体板数" : "只展示今日首板股票";
                return (
                  <section
                    className={`ladder-layer-v5 full-layer-v5 ${isAbove ? "above-five" : ""} ${expanded ? "expanded" : ""}`}
                    data-layer-key={layer.key}
                    key={layer.key}
                  >
                    <div className="ladder-layer-head-v5">
                      <div className="ladder-title-v5">
                        <b>{label}</b>
                        <span>{subtitle}</span>
                      </div>
                      <div className="ladder-head-meta-v5">
                        <span className="count">{layer.stocks.length} 只</span>
                      </div>
                    </div>
                    <div className="ladder-body-v5">
                      <div className="stock-grid-v5">{layer.stocks.map((stock) => renderCard(stock, isAbove ? "above" : "normal"))}</div>
                      {needExpand ? (
                        <button className="ladder-expand-v5" type="button" data-layer-key={layer.key} onClick={() => toggleLayer(layer.key)}>
                          <span className="arrows">{expanded ? "⌃⌃" : "⌄⌄"}</span>
                          <span>{expanded ? "收起" : "展开全部"}</span>
                        </button>
                      ) : null}
                    </div>
                  </section>
                );
              }

              const needExpand = layer.previousStocks.length + layer.currentStocks.length > 12;
              return (
                <section className={`ladder-layer-v5 promotion-layer ${expanded ? "expanded" : ""}`} data-layer-key={layer.key} key={layer.key}>
                  <div className="ladder-layer-head-v5">
                    <div className="ladder-title-v5">
                      <b>
                        {layer.previousLabel} → {layer.currentLabel}
                      </b>
                      <span>左侧为昨日层级全量，右侧为今日晋级成功</span>
                    </div>
                    <div className="ladder-head-meta-v5">
                      <span className="count">昨日 {layer.previousStocks.length} 只</span>
                      <span className="count">晋级 {layer.currentStocks.length} 只</span>
                    </div>
                  </div>
                  <div className="ladder-body-v5">
                    <div className="promotion-body-v5">
                      {renderSide(layer.previousLabel, layer.previousStocks)}
                      <div className="ladder-arrow-v5" aria-hidden="true">
                        <span>→</span>
                      </div>
                      {renderSide(layer.currentLabel, layer.currentStocks)}
                    </div>
                    {needExpand ? (
                      <button className="ladder-expand-v5" type="button" data-layer-key={layer.key} onClick={() => toggleLayer(layer.key)}>
                        <span className="arrows">{expanded ? "⌃⌃" : "⌄⌄"}</span>
                        <span>{expanded ? "收起" : "展开全部"}</span>
                      </button>
                    ) : null}
                  </div>
                </section>
              );
            })}
          </>
        ) : (
          <div className="ladder-empty-v5">暂无连板天梯数据</div>
        )}
      </div>
    </Panel>
  );
}
