interface BreadcrumbProps {
  onAction: (message: string) => void;
}

export function Breadcrumb({ onAction }: BreadcrumbProps) {
  return (
    <div className="breadcrumb" aria-label="Breadcrumb">
      <button type="button" onClick={() => onAction("跳转：/")}>
        财势乾坤
      </button>
      <span>/</span>
      <button type="button" onClick={() => onAction("跳转：/market")}>
        乾坤行情
      </button>
      <span>/</span>
      <span className="current">市场总览</span>
    </div>
  );
}
