import { useRef, useState, type KeyboardEvent } from "react";

import type { IndexDetailWeightsResponseDto } from "../api/indexDetailApiTypes";
import { formatNullablePoint, formatNullableSignedPercent, formatNullableSignedPoint, marketDirectionClass } from "../api/indexDetailViewModelAdapter";
import type { IndexDetailViewModel, IndexInfoTab, IndexModulePhase, IndexPagePhase, TrendChannelViewModel } from "../model/indexDetailTypes";
import { IndexDetailPartialNotice } from "../state/IndexDetailPartialNotice";
import { IndexBasicTab } from "./IndexBasicTab";
import { IndexTechnicalTab } from "./IndexTechnicalTab";
import { IndexWeightsTab } from "./IndexWeightsTab";

const TABS: Array<{ key: IndexInfoTab; label: string }> = [
  { key: "basic", label: "基本行情" }, { key: "weights", label: "权重股贡献" }, { key: "technical", label: "技术面" },
];

interface IndexInfoRailProps {
  activeTab: IndexInfoTab;
  onAction: (message: string) => void;
  onTrendRetry: () => void;
  onTabChange: (tab: IndexInfoTab) => void;
  pagePhase: Extract<IndexPagePhase, "ready" | "delayed" | "partial" | "empty">;
  partialReasons: string[];
  trend: TrendChannelViewModel | null;
  trendPhase: "unavailable" | "loading" | "ready" | "error";
  viewModel: IndexDetailViewModel;
  weights: { data: IndexDetailWeightsResponseDto | null; errorMessage: string; phase: IndexModulePhase; retry: () => void };
}

export function IndexInfoRail({ activeTab, onAction, onTabChange, onTrendRetry, pagePhase, partialReasons, trend, trendPhase, viewModel, weights }: IndexInfoRailProps) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [weightsScrollTop, setWeightsScrollTop] = useState(0);
  const tone = marketDirectionClass(viewModel.quote.direction);
  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + TABS.length) % TABS.length;
    onTabChange(TABS[nextIndex].key);
    tabRefs.current[nextIndex]?.focus();
  }
  return (
    <aside className="index-detail-info-rail" aria-label="指数右侧信息栏">
      <section className="index-header" aria-label="IndexHeader">
        <div className="index-header-summary"><div><h2>{viewModel.identity.name}</h2><span>{viewModel.identity.tsCode}</span></div><div className="index-header-price"><b className={tone}>{formatNullablePoint(viewModel.quote.point)}</b><span className={tone}>{formatNullableSignedPoint(viewModel.quote.change)} {formatNullableSignedPercent(viewModel.quote.changePct)}</span></div></div>
        <div className="index-header-actions"><button type="button" onClick={() => onAction("+自选暂未开通")}>+自选</button><button type="button" onClick={() => onAction("+提醒暂未开通")}>+提醒</button><button type="button" onClick={() => onAction("交易计划暂未开通")}>+交易计划</button></div>
      </section>
      <div className="index-right-tabs" role="tablist" aria-label="指数信息页签">
        {TABS.map((tab, index) => <button aria-controls={`index-tab-${tab.key}`} aria-selected={activeTab === tab.key} className={activeTab === tab.key ? "active" : ""} key={tab.key} onClick={() => onTabChange(tab.key)} onKeyDown={(event) => onTabKeyDown(event, index)} ref={(node) => { tabRefs.current[index] = node; }} role="tab" tabIndex={activeTab === tab.key ? 0 : -1} type="button">{tab.label}</button>)}
      </div>
      <div className="index-right-tab-content" id={`index-tab-${activeTab}`} role="tabpanel">
        {activeTab === "basic" ? <IndexBasicTab metrics={viewModel.basicMetrics} statusLabel={pagePhase === "empty" ? "暂无数据" : "日线口径"} /> : null}
        {activeTab === "weights" ? <IndexWeightsTab {...weights} onRetry={weights.retry} onScrollTopChange={setWeightsScrollTop} scrollTop={weightsScrollTop} /> : null}
        {activeTab === "technical" ? <IndexTechnicalTab onTrendRetry={onTrendRetry} trend={trend} trendPhase={trendPhase} viewModel={viewModel} /> : null}
      </div>
      {pagePhase === "partial" ? <IndexDetailPartialNotice reasons={partialReasons} variant="partial" /> : null}
      {pagePhase === "delayed" ? <IndexDetailPartialNotice expectedTradeDate={viewModel.dataStatus.expectedTradeDate} observedTradeDate={viewModel.dataStatus.observedTradeDate} variant="delayed" /> : null}
    </aside>
  );
}
