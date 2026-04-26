import type { OpsFreshnessResponse } from "../shared/api/types";

export function buildFreshnessDisplayNameMap(freshness?: OpsFreshnessResponse): Record<string, string> {
  const map: Record<string, string> = {};
  for (const group of freshness?.groups || []) {
    for (const item of group.items || []) {
      map[item.dataset_key] = item.display_name;
    }
  }
  return map;
}
