import type { WatchlistGroupMarkDto } from "../api/watchlistApiTypes";
export function WatchlistColorMarks({
  marks
}: {
  marks: WatchlistGroupMarkDto[];
}) {
  return <div className="watchlist-color-marks" style={{
    gridTemplateRows: marks.length ? `repeat(${marks.length}, 1fr)` : undefined
  }}>
    {marks.map(mark => <span key={mark.groupId} title={`属于分组：${mark.name}`} aria-label={`属于分组：${mark.name}`} style={{
      backgroundColor: mark.color
    }} />)}
  </div>;
}
