import type { StockIdentity } from "../model/stockDetailTypes";
import { DetailReturnHomeButton } from "../../../shared/ui/detail-return-home/DetailReturnHomeButton";

interface StockBreadcrumbActionBarProps {
  onReturnHome: () => void;
  stock: StockIdentity;
}

export function StockBreadcrumbActionBar({ onReturnHome, stock }: StockBreadcrumbActionBarProps) {
  return (
    <section className="stock-detail-breadcrumb-action-bar" aria-label="BreadcrumbActionBar">
      <div className="stock-detail-breadcrumb" aria-label="路径">
        <span>财势乾坤</span>
        <span>/</span>
        <span>乾坤行情</span>
        <span>/</span>
        <strong>个股详情</strong>
        <span>/</span>
        <strong className="stock-name">
          {stock.name} {stock.tsCode}
        </strong>
      </div>
      <DetailReturnHomeButton onReturnHome={onReturnHome} />
    </section>
  );
}
