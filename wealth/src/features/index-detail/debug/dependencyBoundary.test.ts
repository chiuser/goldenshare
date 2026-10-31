import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

it("ordinary entry files have no runtime imports of the research or debug implementation", () => {
  const root = resolve(import.meta.dirname, "../../..");
  const files = [
    "pages/index-detail/IndexDetailPage.tsx",
    ...["IndexChartWorkspace.tsx", "IndexMinuteChartWorkspace.tsx"].map(p => `features/index-detail/chart/${p}`),
    ...["xxm", "xxm-forecast"].flatMap(dir => ["apiClient.ts", "adapter.ts", dir === "xxm" ? "useIndexXxmLayer.ts" : "useXxmForecast.ts"]
      .map(p => `features/index-detail/${dir}/${p}`)),
  ];
  for (const path of files) {
    const source = readFileSync(resolve(root, path), "utf8");
    const imports = [...source.matchAll(/import\s+[^;]*?\s+from\s+["'][^"']+["'];/g)].map(m => m[0]);
    for (const statement of imports) {
      if (statement.includes("/debug/") || statement.includes("/daily-wave/")) {
        expect(statement, path).toMatch(/^import\s+type\s/);
        expect(statement, path).toContain("/debug/types");
      }
    }
    expect(source, path).not.toMatch(/import\s*\([^)]*(daily-wave|\/debug\/)/);
  }
});
