import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import ts from "typescript";
import { expect, it } from "vitest";

// LLD 22.15 F09: inspect dependency paths, not source formatting/import counts.
const root = resolve(import.meta.dirname, "../../..");
const debugRoot = resolve(root, "features/index-detail/debug");
const waveRoot = resolve(root, "features/index-detail/daily-wave");
const loaderPath = "pages/index-detail/useIndexDebugModule.ts";
const debugEntry = resolve(root, "pages/index-detail/IndexDetailDebugPage");
type Dependency = { module: string; runtime: boolean; dynamic: boolean };
function dependencies(source: string): Dependency[] {
  const file = ts.createSourceFile("entry.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const result: Dependency[] = [];
  function visit(node: ts.Node) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const clause = node.importClause;
      const bindings = clause?.namedBindings;
      const typeOnly = clause?.isTypeOnly || !!(clause && !clause.name && bindings &&
        ts.isNamedImports(bindings) && bindings.elements.length && bindings.elements.every(item => item.isTypeOnly));
      result.push({ module: node.moduleSpecifier.text, runtime: !typeOnly, dynamic: false });
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword &&
               node.arguments[0] && ts.isStringLiteralLike(node.arguments[0])) {
      result.push({ module: node.arguments[0].text, runtime: true, dynamic: true });
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return result;
}
function target(path: string, dependency: Dependency) {
  return dependency.module.startsWith(".")
    ? resolve(dirname(resolve(root, path)), dependency.module)
    : dependency.module;
}
function auxiliary(path: string) {
  return path === debugEntry || [debugRoot, waveRoot].some(dir => path === dir || path.startsWith(dir + "/"));
}
function violations(path: string, source: string) {
  return dependencies(source).filter(dep => {
    if (!dep.runtime || !auxiliary(target(path, dep))) return false;
    if (path === loaderPath) return !dep.dynamic;
    return true;
  });
}

it("ordinary entries do not load auxiliary implementations", () => {
  const files = [
    "pages/index-detail/IndexDetailPage.tsx", "pages/index-detail/IndexDetailPageView.tsx", "app/routes/WealthRouter.tsx",
    ...["IndexChartWorkspace.tsx", "IndexMinuteChartWorkspace.tsx"].map(p => `features/index-detail/chart/${p}`),
    ...["xxm", "xxm-forecast"].flatMap(dir => ["apiClient.ts", "adapter.ts", dir === "xxm" ? "useIndexXxmLayer.ts" : "useXxmForecast.ts"]
      .map(p => `features/index-detail/${dir}/${p}`)),
  ];
  for (const path of files) expect(violations(path, readFileSync(resolve(root, path), "utf8")), path).toEqual([]);
});

it("the loader dynamically loads the auxiliary component without static auxiliary dependencies", () => {
  const source = readFileSync(resolve(root, loaderPath), "utf8");
  expect(violations(loaderPath, source)).toEqual([]);
  expect(dependencies(source).some(dep => dep.dynamic && target(loaderPath, dep) ===
    debugEntry)).toBe(true);
});

it("allows type-only imports, normal helpers and formatting changes", () => {
  const source = `import { useEffect } from 'react';
    import { helper } from '../shared/helper';
    import type { Debug } from '../debug/types';
    import { type Wave } from '../daily-wave/types';`;
  expect(violations("features/index-detail/xxm/adapter.ts", source)).toEqual([]);
  expect(dependencies(source).map(dep => [dep.module, dep.runtime])).toEqual([
    ["react", true], ["../shared/helper", true], ["../debug/types", false], ["../daily-wave/types", false],
  ]);
  expect(violations("pages/index-detail/IndexDetailPage.tsx", `import {
    useIndexDebugModule
  } from './useIndexDebugModule'`)).toEqual([]);
  expect(violations(loaderPath, "import { useEffect } from 'react'; import { helper } from '../shared/helper';")).toEqual([]);
});

it("rejects runtime auxiliary imports including side effects and dynamic calls in ordinary entries", () => {
  const source = `import '../debug/IndexRecognitionDebug';
    import { review } from '../daily-wave/apiClient';
    const load = () => import ( '../debug/IndexRecognitionDebug' );`;
  expect(violations("features/index-detail/xxm/adapter.ts", source).map(dep => dep.module)).toEqual([
    "../debug/IndexRecognitionDebug", "../daily-wave/apiClient", "../debug/IndexRecognitionDebug",
  ]);
  expect(violations(loaderPath, "import { render } from './IndexDetailDebugPage';")).toHaveLength(1);
});
