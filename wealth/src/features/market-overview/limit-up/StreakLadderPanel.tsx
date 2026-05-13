import { useMemo, useState } from "react";
import { Panel } from "../../../shared/ui/Panel";
import type { LadderV5PromotionLayer, LadderV5Stock, MarketOverview } from "../api/marketOverviewTypes";

interface StreakLadderPanelProps {
  overview: MarketOverview;
  ladder?: MarketOverview["ladderV5"];
  viewState?: "loading" | "ready" | "error";
  errorMessage?: string;
  onAction: (message: string) => void;
}

const FIRST_LAYER_COLLAPSED_VISIBLE_COUNT = 12;

export function StreakLadderPanel({ overview, ladder, viewState = "ready", errorMessage, onAction }: StreakLadderPanelProps) {
  const [expandedLayers, setExpandedLayers] = useState<Set<string>>(new Set());
  const ladderData = ladder ?? overview.ladderV5;

  const layers = useMemo(() => {
    if (!ladderData) return [];

    const next: Array<
      | { type: "above"; key: string; stocks: LadderV5Stock[] }
      | { type: "first"; key: string; stocks: LadderV5Stock[] }
      | ({ type: "promotion"; key: string } & LadderV5PromotionLayer)
    > = [];

    if (ladderData.highestStreakLevel >= 6) {
      next.push({ type: "above", key: "aboveFive", stocks: ladderData.aboveFive });
    }

    const maxNormal = Math.min(ladderData.highestStreakLevel, 5);
    for (let level = maxNormal; level >= 2; level -= 1) {
      const promotion = ladderData.promotions[level];
      if (promotion) next.push({ type: "promotion", key: `promotion-${level}`, ...promotion });
    }

    if (ladderData.highestStreakLevel >= 1) {
      next.push({ type: "first", key: "first", stocks: ladderData.firstBoard });
    }
    return next;
  }, [ladderData]);

  const toggleLayer = (key: string) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const clsBy = (value: number | null) => {
    if (value === null) return "flat";
    if (value > 0) return "up";
    if (value < 0) return "down";
    return "flat";
  };

  const fmtPct = (value: number) => (value >= 0 ? `+${value.toFixed(2)}%` : `${value.toFixed(2)}%`);

  const renderCard = (stock: LadderV5Stock, mode: "above" | "normal") => {
    const pctClass = clsBy(stock.changePct);
    const advClass = mode === "above" ? "above" : stock.advanced ? "advanced" : "not-advanced";
    const quoteUnavailable = stock.quoteStatus !== "READY";
    const priceText =
      stock.quoteStatus === "SUSPENDED"
        ? "停牌"
        : stock.latestPrice !== null && Number.isFinite(stock.latestPrice)
          ? stock.latestPrice.toFixed(2)
          : "--";
    const titleText = quoteUnavailable
      ? `${stock.stockName}｜${stock.stockCode}｜${priceText}`
      : `点击进入个股详情：${stock.stockName}｜${stock.stockCode}｜最新价 ${priceText}｜${stock.limitAmountLabel} ${stock.limitAmountDisplayText}｜${stock.streakText}`;
    return (
      <article
        className={`stock-compact-card-v5 ${advClass} ${quoteUnavailable ? "quote-unavailable" : ""}`}
        key={`${stock.stockCode}-${stock.currentStreakLevel}`}
        title={titleText}
        onClick={() => onAction(`进入个股详情：${stock.stockCode}`)}
      >
        <span className="stock-card-code-v5">{stock.stockCode}</span>
        <div className="stock-card-split-v7">
          <div className="stock-card-zone-v7 left">
            <span className="stock-card-name-v5">{stock.stockName}</span>
            <span className={`stock-card-price-v5 num ${pctClass}`}>{priceText}</span>
          </div>
          {quoteUnavailable ? null : (
            <>
              <div className="stock-card-zone-v7 mid">
                <span className={`stock-card-change-v5 num ${pctClass}`}>
                  {stock.changePct !== null && Number.isFinite(stock.changePct) ? fmtPct(stock.changePct) : "--"}
                </span>
                <span className="stock-card-board-amount-v6">{stock.limitAmountDisplayText}</span>
              </div>
              <div className="stock-card-zone-v7 right">
                <span className="stock-card-sector-v5">{stock.sectorName ?? "--"}</span>
                <span className="stock-card-meta-v5">{stock.streakText}</span>
              </div>
            </>
          )}
        </div>
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
        {viewState === "loading" ? (
          <div className="ladder-empty-v5">loading</div>
        ) : viewState === "error" ? (
          <div className="ladder-empty-v5">{errorMessage ?? "连板天梯加载失败"}</div>
        ) : ladderData ? (
          <>
            <div className="ladder-v5-summary">
              <div>
                <strong>{ladderData.tradeDate} 连板天梯</strong>
              </div>
            </div>
            {layers.map((layer) => {
              const expanded = expandedLayers.has(layer.key);
              if (layer.type === "above" || layer.type === "first") {
                const isAbove = layer.type === "above";
                const needExpand = layer.type === "first" && layer.stocks.length > FIRST_LAYER_COLLAPSED_VISIBLE_COUNT;
                const visibleStocks =
                  layer.type === "first" && !expanded
                    ? layer.stocks.slice(0, FIRST_LAYER_COLLAPSED_VISIBLE_COUNT)
                    : layer.stocks;
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
                      <div className="stock-grid-v5">{visibleStocks.map((stock) => renderCard(stock, isAbove ? "above" : "normal"))}</div>
                      {needExpand ? (
                        <button className="ladder-expand-v5" type="button" data-layer-key={layer.key} onClick={() => toggleLayer(layer.key)}>
                          <span className={`arrows ${expanded ? "is-up" : "is-down"}`} aria-hidden="true">
                            <span className="arrow-line">{expanded ? "▴" : "▾"}</span>
                            <span className="arrow-line">{expanded ? "▴" : "▾"}</span>
                          </span>
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
                        <span className={`arrows ${expanded ? "is-up" : "is-down"}`} aria-hidden="true">
                          <span className="arrow-line">{expanded ? "▴" : "▾"}</span>
                          <span className="arrow-line">{expanded ? "▴" : "▾"}</span>
                        </span>
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
