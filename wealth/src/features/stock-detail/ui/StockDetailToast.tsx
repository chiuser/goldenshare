interface StockDetailToastProps {
  message: string;
}

export function StockDetailToast({ message }: StockDetailToastProps) {
  return (
    <div aria-live="polite" className={message ? "stock-detail-toast show" : "stock-detail-toast"}>
      {message || " "}
    </div>
  );
}
