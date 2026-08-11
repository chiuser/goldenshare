import type { IndexDetailViewModel } from "../model/indexDetailTypes";

export function IndexBreadcrumbActionBar({ identity }: { identity: IndexDetailViewModel["identity"] }) {
  return (
    <section className="index-detail-breadcrumb-bar" aria-label="BreadcrumbActionBar">
      <div className="index-detail-breadcrumb" aria-label="路径">
        <span>财势乾坤</span><span>/</span><span>乾坤行情</span><span>/</span><strong>指数详情</strong><span>/</span>
        <strong className="current-index">{identity.name} {identity.tsCode}</strong>
      </div>
    </section>
  );
}
