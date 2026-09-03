import { useEffect, useState } from "react";
import {
  buildIndexDetailPath,
  buildStockDetailPath,
  DEFAULT_WEALTH_PATH,
  navigateWealth,
  resolveTopMarketNavPath,
} from "../../app/routes/routerState";
import { useWatchlistController } from "../../features/watchlist/model/useWatchlistController";
import { useWatchlistTickers } from "../../features/watchlist/model/useWatchlistTickers";
import { AddWatchlistDialog } from "../../features/watchlist/ui/AddWatchlistDialog";
import { RemoveWatchlistDialog } from "../../features/watchlist/ui/RemoveWatchlistDialog";
import { WatchlistTable } from "../../features/watchlist/ui/WatchlistTable";
import { Panel } from "../../shared/ui/Panel";
import { PageBreadcrumb } from "../../shared/ui/page-breadcrumb/PageBreadcrumb";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import "./watchlist-page.css";

export function WatchlistPage({ search = "" }: { search?: string }) {
  const tradeDate = new URLSearchParams(search).get("tradeDate") ?? undefined;
  const controller = useWatchlistController(tradeDate);
  const tickers = useWatchlistTickers(tradeDate);
  const [addOpen, setAddOpen] = useState(false);
  const [toast, setToast] = useState("");
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);
  const dataStatus = controller.dataStatus;
  const openAdd = () => setAddOpen(true);
  return (
    <div className="watchlist-page">
      <TopMarketBar
        activeNav="market"
        tickers={tickers}
        onTickerSelect={(code) => navigateWealth(buildIndexDetailPath(code))}
        onNavigate={(target) => {
          const path = resolveTopMarketNavPath(target);
          if (path) navigateWealth(path);
          else setToast("该功能暂未开通");
        }}
      />
      <main className="watchlist-page-content">
        <PageBreadcrumb
          items={[
            { label: "财势乾坤", path: DEFAULT_WEALTH_PATH },
            { label: "乾坤行情", path: DEFAULT_WEALTH_PATH },
            { label: "我的自选" },
          ]}
          sessionStatus={controller.pageContext?.sessionStatus ?? "CLOSED"}
          onNavigate={navigateWealth}
        />
        <Panel
          title="我的自选"
          className="watchlist-panel"
          meta={
            <div className="watchlist-header-meta">
              <span className="watchlist-count num">
                {controller.viewState === "loading" ||
                controller.viewState === "error"
                  ? "--"
                  : controller.totalCount}{" "}
                只
              </span>
              <span className="watchlist-date">
                数据日期{" "}
                <span className="num">
                  {dataStatus?.observedTradeDate ?? "--"}
                </span>
              </span>
              <button
                className="watchlist-add-button"
                type="button"
                onClick={openAdd}
              >
                + 添加自选
              </button>
            </div>
          }
        >
          {controller.viewState === "loading" && (
            <div
              className="watchlist-page-state"
              role="status"
              aria-label="自选加载中"
            >
              <span>正在加载自选股票…</span>
            </div>
          )}
          {controller.viewState === "error" && (
            <div className="watchlist-page-state" role="alert">
              <h2>自选列表暂不可用</h2>
              <p>{controller.errorMessage}</p>
              {controller.canRetry && (
                <button type="button" onClick={() => void controller.retry()}>
                  重试
                </button>
              )}
            </div>
          )}
          {controller.viewState === "empty" && (
            <div className="watchlist-page-state">
              <h2>还没有自选股票</h2>
              <p>添加你关注的股票，快速查看行情。</p>
              <button
                className="watchlist-add-button"
                type="button"
                onClick={openAdd}
              >
                + 添加第一只自选股
              </button>
            </div>
          )}
          {controller.viewState === "ready" && (
            <>
              {(dataStatus?.status === "DELAYED" ||
                dataStatus?.status === "PARTIAL") && (
                <div className="watchlist-data-notice" role="status">
                  {dataStatus.status === "PARTIAL"
                    ? "部分数据缺失，缺失字段以 -- 展示。"
                    : "行情数据延迟，当前展示实际数据日期的行情。"}
                </div>
              )}
              <WatchlistTable
                rows={controller.items}
                pendingCodes={controller.pendingCodes}
                hasMore={controller.nextCursor !== null}
                loadingMore={controller.isLoadingMore}
                loadMoreError={controller.loadMoreError}
                scrollResetKey={controller.scrollResetKey}
                onLoadMore={controller.loadMore}
                onRetryMore={controller.retryMore}
                onSelect={(code) => navigateWealth(buildStockDetailPath(code))}
                onRemove={controller.requestRemove}
              />
            </>
          )}
        </Panel>
      </main>
      <AddWatchlistDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onAdd={controller.appendAddedItem}
        pendingCodes={controller.pendingCodes}
        memberships={controller.memberships}
      />
      <RemoveWatchlistDialog
        stock={controller.removeTarget}
        open={controller.removeTarget !== null}
        pending={
          controller.removeTarget !== null &&
          controller.pendingCodes.includes(controller.removeTarget.tsCode)
        }
        error={controller.errorMessage}
        onCancel={controller.cancelRemove}
        onConfirm={() => void controller.confirmRemove()}
      />
      {toast && (
        <div className="watchlist-toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
