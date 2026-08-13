import type { IndexDetailViewModel } from "../model/indexDetailTypes";
import { DetailReturnHomeButton } from "../../../shared/ui/detail-return-home/DetailReturnHomeButton";

interface IndexBreadcrumbActionBarProps {
  identity: IndexDetailViewModel["identity"];
  onReturnHome: () => void;
}

export function IndexBreadcrumbActionBar({ identity, onReturnHome }: IndexBreadcrumbActionBarProps) {
  return (
    <section className="index-detail-breadcrumb-bar" aria-label="BreadcrumbActionBar">
      <div className="index-detail-breadcrumb" aria-label="路径">
        <span>财势乾坤</span><span>/</span><span>乾坤行情</span><span>/</span><strong>指数详情</strong><span>/</span>
        <strong className="current-index">{identity.name} {identity.tsCode}</strong>
      </div>
      <DetailReturnHomeButton onReturnHome={onReturnHome} />
    </section>
  );
}
