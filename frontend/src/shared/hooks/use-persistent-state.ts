import { useEffect, useState } from "react";


function readValue<T>(key: string, initialValue: T): T {
  if (typeof window === "undefined") {
    return initialValue;
  }

  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return initialValue;
  }

  try {
    return JSON.parse(raw) as T;
  } catch {
    return initialValue;
  }
}

export function usePersistentState<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => readValue(key, initialValue));

  useEffect(() => {
    window.localStorage.setItem(key, JSON.stringify(value));
  }, [key, value]);

  return [value, setValue] as const;
}
