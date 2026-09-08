import type { WatchlistGroupDto } from "../api/watchlistApiTypes";
export function WatchlistTabs({
  groups,
  currentGroupId,
  locked,
  canCreate,
  onSelect,
  onCreate
}: {
  groups: WatchlistGroupDto[];
  currentGroupId: number;
  locked: boolean;
  canCreate: boolean;
  onSelect: (id: number) => void;
  onCreate: () => void;
}) {
  return <nav className="watchlist-tabs" aria-label="自选分组">
    <div role="tablist" aria-label="自选分组标签">
      {groups.map(group => <button key={group.id} role="tab" type="button" aria-selected={group.id === currentGroupId} disabled={locked && group.id !== currentGroupId} onClick={() => onSelect(group.id)}>
        {group.color && <i className="watchlist-group-dot" style={{
          backgroundColor: group.color
        }} />}{group.name}
      </button>)}
    </div>
    <button type="button" className="watchlist-create-button" disabled={locked || !canCreate} title={!canCreate ? "分组数量已达上限" : undefined} onClick={onCreate}>+ 新建分组</button>
  </nav>;
}
