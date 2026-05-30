import { useState } from "react";

import { directionClass } from "../../../shared/lib/marketDirection";
import { formatPoint, formatSignedPercent } from "../../../shared/lib/formatters";
import type { StockDetailViewModel } from "../model/stockDetailTypes";

interface StockInfoRailProps {
  viewModel: StockDetailViewModel;
  onAction: (message: string) => void;
}

export function StockInfoRail({ viewModel, onAction }: StockInfoRailProps) {
  const [activeTab, setActiveTab] = useState<"quote" | "profile">("quote");
  const quoteDirection = directionClass(viewModel.quote.direction);

  return (
    <aside className="stock-detail-info-rail" aria-label="右侧信息栏">
      <section className="right-stock-header" aria-label="StockHeader">
        <div className="stock-header-summary">
          <div className="stock-header-identity">
            <div className="stock-name-line">
              <h2>{viewModel.stock.name}</h2>
              {viewModel.stock.tags.map((tag) => (
                <span className="tag" key={tag}>
                  {tag}
                </span>
              ))}
            </div>
            <div className="stock-code-line">{viewModel.stock.tsCode}</div>
          </div>
          <div className="right-price">
            <div className={`price ${quoteDirection}`}>{formatPoint(viewModel.quote.price)}</div>
            <div className={`chg ${quoteDirection}`}>
              {viewModel.quote.change > 0 ? "+" : ""}
              {formatPoint(viewModel.quote.change)} {formatSignedPercent(viewModel.quote.changePct)}
            </div>
          </div>
        </div>
        <div className="stock-header-actions" aria-label="个股操作">
          {["+自选", "+提醒", "+交易计划"].map((label) => (
            <button className="stock-header-action" key={label} type="button" onClick={() => onAction(`${label}暂未开通`)}>
              {label}
            </button>
          ))}
        </div>
      </section>

      <div className="right-tabs" role="tablist">
        <button
          className={activeTab === "quote" ? "right-tab active" : "right-tab"}
          role="tab"
          type="button"
          onClick={() => setActiveTab("quote")}
        >
          盘口
        </button>
        <button
          className={activeTab === "profile" ? "right-tab active" : "right-tab"}
          role="tab"
          type="button"
          onClick={() => setActiveTab("profile")}
        >
          资料
        </button>
      </div>

      <div className="right-tab-content">
        {activeTab === "quote" ? (
          <section className="tab-pane active" id="quotePane">
            <QuoteSummary viewModel={viewModel} />
            <RelatedSectorTable viewModel={viewModel} />
            <StockMoneyFlowPanel viewModel={viewModel} />
            <ProductBoundaryNotes notes={viewModel.rightRail.productBoundaryNotes} />
          </section>
        ) : (
          <section className="tab-pane active" id="profilePane">
            <div className="profile-placeholder">
              <b>资料页签</b>
              <span>公司资料、财务摘要与公告入口将在后续真实 API 方案中接入。</span>
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}

function QuoteSummary({ viewModel }: { viewModel: StockDetailViewModel }) {
  const quote = viewModel.quote;
  return (
    <div className="side-section">
      <div className="side-section-title">
        盘口摘要 <small>不含五档盘口</small>
      </div>
      <div className="quote-summary-grid">
        <div className="quote-cell">
          <span>今开</span>
          <b>{formatPoint(quote.open)}</b>
        </div>
        <div className="quote-cell">
          <span>昨收</span>
          <b>{formatPoint(quote.prevClose)}</b>
        </div>
        <div className="quote-cell">
          <span>最高</span>
          <b className="up">{formatPoint(quote.high)}</b>
        </div>
        <div className="quote-cell">
          <span>最低</span>
          <b className="down">{formatPoint(quote.low)}</b>
        </div>
        <div className="quote-cell">
          <span>换手率</span>
          <b>{quote.turnoverRate.toFixed(2)}%</b>
        </div>
        <div className="quote-cell">
          <span>量比</span>
          <b>{quote.volumeRatio.toFixed(2)}</b>
        </div>
        <div className="quote-cell">
          <span>成交量</span>
          <b>{quote.volumeText}</b>
        </div>
        <div className="quote-cell">
          <span>成交额</span>
          <b>{quote.amountText}</b>
        </div>
      </div>
    </div>
  );
}

function RelatedSectorTable({ viewModel }: { viewModel: StockDetailViewModel }) {
  return (
    <div className="side-section" aria-label="关联板块表">
      <div className="side-section-title">
        关联板块 <small>点击进入板块行情</small>
      </div>
      <table className="sector-table">
        <tbody>
          {viewModel.rightRail.sectors.map((sector) => (
            <tr key={`${sector.type}-${sector.name}`}>
              <td className="name">{sector.name}</td>
              <td className={directionClass(sector.direction)}>{formatSignedPercent(sector.pct)}</td>
              <td>{sector.count}</td>
              <td>{sector.type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StockMoneyFlowPanel({ viewModel }: { viewModel: StockDetailViewModel }) {
  return (
    <div className="side-section" aria-label="个股资金统计">
      <div className="side-section-title">
        个股资金统计 <small>单位：万元</small>
      </div>
      <div className="money-summary">
        <div className="donut" aria-label="环形资金分布图" />
        <div className="money-bars">
          {viewModel.rightRail.moneyFlow.map((row) => (
            <div className="money-row" key={row.label}>
              <span>{row.label}</span>
              <i className="bar-track">
                <em className={`bar-fill ${directionClass(row.direction)}`} style={{ width: `${row.ratio}%` }} />
              </i>
              <b className={directionClass(row.direction)}>
                {row.value > 0 ? "+" : ""}
                {row.value}
              </b>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ProductBoundaryNotes({ notes }: { notes: string[] }) {
  return (
    <div className="side-section">
      <div className="side-section-title">
        产品边界 <small>P0</small>
      </div>
      <ul className="boundary-notes">
        {notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </div>
  );
}
