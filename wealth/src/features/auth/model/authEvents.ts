export const WEALTH_AUTH_REQUIRED_EVENT = "wealth-auth-required";

export function notifyAuthRequired() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(WEALTH_AUTH_REQUIRED_EVENT));
}

