import { useEffect, useRef, useState } from "react";
import { buildIndexDetailPath, buildStockDetailPath, DEFAULT_WEALTH_PATH, navigateWealth, resolveTopMarketNavPath } from "../../app/routes/routerState";
import { fetchStockWatchlistGroups, WatchlistApiError } from "../../features/watchlist/api/watchlistApi";
import type { WatchlistBatchAction } from "../../features/watchlist/api/watchlistApiTypes";
import { useWatchlistGroupsController } from "../../features/watchlist/model/useWatchlistGroupsController";
import { useWatchlistItemsController } from "../../features/watchlist/model/useWatchlistItemsController";
import { useWatchlistEditController } from "../../features/watchlist/model/useWatchlistEditController";
import { mutationLocked, watchlistError } from "../../features/watchlist/model/watchlistTypes";
import { useWatchlistTickers } from "../../features/watchlist/model/useWatchlistTickers";
import { AddWatchlistDialog } from "../../features/watchlist/ui/AddWatchlistDialog";
import { WatchlistTabs } from "../../features/watchlist/ui/WatchlistTabs";
import { WatchlistEditToolbar } from "../../features/watchlist/ui/WatchlistEditToolbar";
import { CreateWatchlistGroupDialog } from "../../features/watchlist/ui/CreateWatchlistGroupDialog";
import { ChangeWatchlistGroupColorDialog } from "../../features/watchlist/ui/ChangeWatchlistGroupColorDialog";
import { WatchlistGroupTargetDialog } from "../../features/watchlist/ui/WatchlistGroupTargetDialog";
import { ConfirmWatchlistRemoveDialog } from "../../features/watchlist/ui/ConfirmWatchlistRemoveDialog";
import { ConfirmWatchlistGroupDeleteDialog } from "../../features/watchlist/ui/ConfirmWatchlistGroupDeleteDialog";
import { WatchlistTable } from "../../features/watchlist/ui/WatchlistTable";
import { Panel } from "../../shared/ui/Panel";
import { PageBreadcrumb } from "../../shared/ui/page-breadcrumb/PageBreadcrumb";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import "./watchlist-page.css";
export function WatchlistPage({
  search = ""
}: {
  search?: string;
}) {
  const tradeDate = new URLSearchParams(search).get("tradeDate") ?? undefined;
  const groups = useWatchlistGroupsController();
  const items = useWatchlistItemsController(groups.currentGroupId, tradeDate);
  const ready = groups.state.kind === "ready" ? groups.state : null;
  const group = ready?.groups.find(g => g.id === ready.currentGroupId);
  const edit = useWatchlistEditController(groups.currentGroupId, items.items.map(row => row.membershipId), ready?.rules.maxBatchMemberships ?? 0);
  const tickers = useWatchlistTickers(tradeDate);
  const [addOpen, setAddOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  const membershipReader = useRef<((tsCode: string) => Promise<boolean>) | null>(null);
  const reconciliation = useRef<Promise<boolean> | null>(null);
  const lastUnknown = useRef<object | null>(null);
  const locked = mutationLocked(groups.mutation) || mutationLocked(items.mutation) || mutationLocked(edit.mutation);
  const unknown = groups.mutation.kind === "unknown" || items.mutation.kind === "unknown" || edit.mutation.kind === "unknown";
  const dataStatus = items.dataStatus;
  async function refreshAll(targetId?: number) {
    const before = groups.currentGroupId;
    const result = await groups.refresh(targetId);
    if (!result) return false;
    if (result.currentGroupId !== before) {
      edit.clear();
      edit.finish();
      setAddOpen(false);
      return true;
    }
    return items.reload();
  }
  function reconcile() {
    if (reconciliation.current) return reconciliation.current;
    const task = reconcileFacts().finally(() => {
      reconciliation.current = null;
    });
    reconciliation.current = task;
    return task;
  }
  async function reconcileFacts() {
    const addedAction = items.mutation.kind === "unknown" ? items.mutation.action : null;
    const before = groups.currentGroupId;
    const result = await groups.refresh();
    if (!result) return false;
    if (result.currentGroupId === before && !(await items.reload())) return false;
    if (addedAction && result.groups.some(g => g.id === addedAction.groupId)) {
      try {
        if (membershipReader.current) {
          if (!(await membershipReader.current(addedAction.tsCode))) return false;
        } else await fetchStockWatchlistGroups(addedAction.tsCode);
      } catch (failure) {
        setFeedback(watchlistError(failure).message);
        return false;
      }
    }
    groups.reconciled();
    items.reconciled();
    edit.reconciled();
    edit.clear();
    setCreateOpen(false);
    if (result.currentGroupId !== before) {
      edit.finish();
      setAddOpen(false);
    }
    setFeedback("已读取最新状态，请按当前信息继续操作。");
    return true;
  }
  const unknownAction = groups.mutation.kind === "unknown" ? groups.mutation.action : items.mutation.kind === "unknown" ? items.mutation.action : edit.mutation.kind === "unknown" ? edit.mutation.action : null;
  useEffect(() => {
    if (unknownAction && lastUnknown.current !== unknownAction) {
      lastUnknown.current = unknownAction;
      void reconcile();
    }
  }, [unknownAction]);
  useEffect(() => {
    if (items.errorCode === "WL_GROUP_NOT_FOUND") {
      edit.clear();
      edit.finish();
      setAddOpen(false);
      void groups.refresh();
    }
  }, [items.errorCode]); // The disappearing group is resolved from a fresh group list.

  async function groupAction(action: Parameters<typeof groups.submit>[0]) {
    try {
      const result = await groups.submit(action);
      if (!result) return;
      setCreateOpen(false);
      edit.clear();
      if ("deletedGroupId" in result) edit.finish();
      setFeedback("deletedGroupId" in result ? `已删除分组，移除 ${result.deletedMemberCount} 条组内关系` : `已${action.type === "create" ? "创建" : "更新"}「${result.name}」，共 ${result.memberCount} 只股票`);
    } catch (failure) {
      if (failure instanceof WatchlistApiError && ["WL_GROUP_LIMIT_REACHED", "WL_DEFAULT_GROUP_IMMUTABLE", "WL_GROUP_NOT_FOUND"].includes(failure.code)) await groups.refresh();
      if (failure instanceof WatchlistApiError && failure.outcome === "UNKNOWN") {
        setFeedback("提交结果待确认，请重试读取最新状态");
      }
      return;
    }
    if (!(await refreshAll())) setFeedback("操作已完成，列表刷新失败，请重试读取。");
  }
  async function batchAction(action: WatchlistBatchAction, targets: number[] = []) {
    try {
      const result = await edit.submit(action, targets);
      if (!result) return;
      setFeedback(`操作已完成：新增 ${result.createdCount} 条，移出 ${result.removedCount} 条，更新 ${result.updatedCount} 条。`);
    } catch (failure) {
      setFeedback(watchlistError(failure).message);
      if (failure instanceof WatchlistApiError && failure.outcome === "UNKNOWN") setFeedback("提交结果待确认，请重试读取最新状态");
      if (failure instanceof WatchlistApiError && failure.code === "WL_SELECTION_STALE") {
        setFeedback("列表已变化，请重新选择。");
        await refreshAll();
      }
      if (failure instanceof WatchlistApiError && failure.code === "WL_TARGET_GROUP_INVALID") await groups.refresh();
      if (failure instanceof WatchlistApiError && failure.code === "WL_GROUP_NOT_FOUND") await refreshAll();
      return;
    }
    if (!(await refreshAll())) setFeedback("操作已完成，列表刷新失败，请重试读取。");
  }
  async function add(code: string) {
    const result = await items.addToCurrentGroup(code);
    if (result && !(await refreshAll())) setFeedback("添加已完成，列表刷新失败，请重试读取。");
    return result;
  }
  const dialogError = edit.dialog === "color" || edit.dialog === "delete" ? groups.mutation.kind === "failed" ? groups.mutation.error.message : undefined : edit.mutation.kind === "failed" ? edit.mutation.error.message : undefined;
  const dialogProps = {
    locked,
    error: unknown ? "提交结果待确认，请读取最新状态。" : dialogError,
    onCancel: () => edit.setDialog(null),
    onRetryRead: unknown ? () => void reconcile() : undefined
  };
  return <div className="watchlist-page">
    <TopMarketBar activeNav="market" tickers={tickers} onTickerSelect={code => navigateWealth(buildIndexDetailPath(code))} onNavigate={target => {
      const path = resolveTopMarketNavPath(target);
      if (path) navigateWealth(path);else setFeedback("该功能暂未开通");
    }} />
    <main className="watchlist-page-content">
      <PageBreadcrumb items={[{
        label: "财势乾坤",
        path: DEFAULT_WEALTH_PATH
      }, {
        label: "乾坤行情",
        path: DEFAULT_WEALTH_PATH
      }, {
        label: "我的自选"
      }]} sessionStatus={items.pageContext?.sessionStatus ?? "CLOSED"} onNavigate={navigateWealth} />
      {groups.state.kind === "loading" && <div role="status" className="watchlist-page-state">正在加载自选分组…</div>}
      {groups.state.kind === "error" && <div role="alert" className="watchlist-page-state"><h2>自选分组暂不可用</h2><p>{groups.state.message}</p><button type="button" onClick={() => void (unknown ? reconcile() : refreshAll())}>重试读取</button></div>}
      {ready && group && <>
        <WatchlistTabs groups={ready.groups} currentGroupId={group.id} locked={edit.isEditing || locked} canCreate={ready.groups.length < ready.rules.maxGroups && ready.groups.filter(g => !g.isDefault).length < ready.rules.maxCustomGroups} onCreate={() => setCreateOpen(true)} onSelect={id => groups.selectGroup(id, edit.isEditing || locked)} />
        <Panel title={group.name} className={`watchlist-panel${group.isDefault ? " is-default-group" : ""}`} meta={<div className="watchlist-header-meta">
          {group.color && <i className="watchlist-group-dot" style={{
            backgroundColor: group.color
          }} />}
          <span className="watchlist-count num">{group.memberCount} 只</span>
          <span className="watchlist-date">数据日期 <span className="num">{dataStatus?.observedTradeDate ?? "--"}</span></span>
          <button className="watchlist-add-button" type="button" disabled={edit.isEditing || locked} onClick={() => setAddOpen(true)}>+ 添加自选</button>
          <button className="watchlist-operation-button" type="button" disabled={edit.isEditing || locked || items.viewState === "loading"} onClick={edit.enter}>{edit.isEditing ? "编辑中" : "操作"}</button>
        </div>}>
          {edit.isEditing && <WatchlistEditToolbar count={edit.selectedIds.size} maxSelection={ready.rules.maxBatchMemberships} isDefault={group.isDefault} locked={locked} onDialog={edit.setDialog} onPin={pin => void batchAction(pin ? "PIN" : "UNPIN")} onDone={edit.finish} />}
          {edit.isEditing && edit.selectedIds.size >= ready.rules.maxBatchMemberships && <div role="status" className="watchlist-data-notice">单次最多选择 {ready.rules.maxBatchMemberships} 只</div>}
          {unknown && <div role="status" className="watchlist-data-notice">提交结果待确认 <button type="button" onClick={() => void reconcile()}>重试读取</button></div>}
          {items.viewState === "loading" && <div role="status" className="watchlist-page-state">正在加载自选股票…</div>}
          {items.viewState === "error" && <div role="alert" className="watchlist-page-state"><h2>自选列表暂不可用</h2><p>{items.errorMessage}</p><button type="button" onClick={() => void (unknown ? reconcile() : items.reload())}>重试读取</button></div>}
          {items.viewState === "empty" && <div className="watchlist-page-state"><h2>当前分组还没有股票</h2><p>添加你关注的股票，快速查看行情。</p><button className="watchlist-add-button" type="button" disabled={edit.isEditing || locked} onClick={() => setAddOpen(true)}>+ 添加第一只自选股</button></div>}
          {items.viewState === "ready" && <>
            {(dataStatus?.status === "DELAYED" || dataStatus?.status === "PARTIAL") && <div className="watchlist-data-notice" role="status">{dataStatus.status === "PARTIAL" ? "部分数据缺失，缺失字段以 -- 展示。" : "行情数据延迟，当前展示实际数据日期的行情。"}</div>}
            <WatchlistTable rows={items.items} editing={edit.isEditing} selectedIds={edit.selectedIds} maxSelection={ready.rules.maxBatchMemberships} locked={locked} sort={items.sort} onSort={items.setSort} onToggle={edit.toggle} hasMore={items.nextCursor !== null} loadingMore={items.isLoadingMore} loadMoreError={items.loadMoreError} scrollResetKey={items.scrollResetKey} onLoadMore={() => void items.loadMore()} onRetryMore={() => void items.loadMore()} onSelect={code => navigateWealth(buildStockDetailPath(code))} />
          </>}
        </Panel>
        <AddWatchlistDialog open={addOpen} groupId={group.id} groupName={group.name} onClose={() => setAddOpen(false)} onAdd={add} mutation={items.mutation} onRetryRead={reconcile} membershipReader={membershipReader} />
      </>}
        <CreateWatchlistGroupDialog open={createOpen} groups={ready?.groups ?? []} rules={ready?.rules} locked={locked} error={groups.mutation.kind === "failed" ? groups.mutation.error.message : unknown ? "提交结果待确认" : undefined} onCancel={() => setCreateOpen(false)} onConfirm={(name, color) => void groupAction({
          type: "create",
          name,
          color
        })} onRetryRead={unknown ? () => void reconcile() : undefined} />
        <WatchlistGroupTargetDialog {...dialogProps} available={!!ready} open={edit.dialog === "move" || edit.dialog === "add"} mode={edit.dialog === "move" ? "move" : "add"} currentGroupId={groups.currentGroupId ?? 0} groups={ready?.groups ?? []} onConfirm={ids => void batchAction(edit.dialog === "move" ? "MOVE" : "ADD_TO_GROUPS", ids)} />
        <ConfirmWatchlistRemoveDialog {...dialogProps} available={!!ready} open={edit.dialog === "remove"} name={group?.name ?? ""} count={edit.selectedIds.size} onConfirm={() => void batchAction("REMOVE")} />
        <ConfirmWatchlistGroupDeleteDialog {...dialogProps} available={!!ready} open={edit.dialog === "delete"} name={group?.name ?? ""} memberCount={group?.memberCount ?? 0} onConfirm={() => group && void groupAction({
          type: "delete",
          groupId: group.id
        })} />
        <ChangeWatchlistGroupColorDialog {...dialogProps} available={!!ready} open={edit.dialog === "color"} name={group?.name ?? ""} color={group?.color ?? null} palette={ready?.rules.palette ?? []} onConfirm={color => group && void groupAction({
          type: "color",
          groupId: group.id,
          color
        })} />
    </main>
    {feedback && <div className="watchlist-toast" role="status">{feedback}</div>}
  </div>;
}
