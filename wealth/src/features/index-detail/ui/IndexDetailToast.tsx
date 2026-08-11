export function IndexDetailToast({ message }: { message: string }) {
  return message ? <div aria-live="polite" className="index-detail-toast" role="status">{message}</div> : null;
}
