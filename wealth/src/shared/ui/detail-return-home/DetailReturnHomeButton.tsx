import "./detail-return-home-button.css";

interface DetailReturnHomeButtonProps {
  onReturnHome: () => void;
}

export function DetailReturnHomeButton({ onReturnHome }: DetailReturnHomeButtonProps) {
  return (
    <button className="detail-return-home" onClick={onReturnHome} type="button">
      <span aria-hidden="true" className="detail-return-home-icon">←</span>
      <span>返回首页</span>
    </button>
  );
}
