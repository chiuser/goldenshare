export function SkeletonBlock() {
  return (
    <div className="state-block">
      <strong>loading</strong>
      <div className="skeleton skeleton-wide" />
      <div className="skeleton skeleton-short" />
    </div>
  );
}
