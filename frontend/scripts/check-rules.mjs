import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const frontendRoot = process.cwd();
const srcRoot = path.join(frontendRoot, "src");

const runtimeExtensions = new Set([".ts", ".tsx", ".css"]);
const ignoredFilePatterns = [/\.test\.(ts|tsx)$/];

const rules = [
  {
    id: "no-week-friday-runtime",
    description: "禁止在运行时代码中继续使用 week_friday 旧业务语义",
    scopePrefixes: ["src/"],
    pattern: /\bweek_friday\b/g,
    allowlist: [],
  },
  {
    id: "no-new-glass-card-in-pages",
    description: "禁止在 pages/** 中新增 glass-card 作为默认页面入口",
    scopePrefixes: ["src/pages/"],
    pattern: /\bglass-card\b/g,
    allowlist: [
      "src/pages/ops-v21-overview-page.tsx",
      "src/pages/ops-v21-source-page.tsx",
      "src/pages/user-overview-page.tsx",
    ],
  },
  {
    id: "no-new-legacy-purple-colors",
    description: "禁止新增旧紫色系色名（violet / grape / pink / magenta）",
    scopePrefixes: ["src/"],
    pattern: /\b(?:violet|grape|pink|magenta)\b/g,
    allowlist: ["src/pages/ops-v21-review-board-page.tsx"],
  },
  {
    id: "no-ops-page-synthetic-layer-snapshot-from-freshness",
    description: "禁止页面层用 freshness 字段伪造 layer snapshot 状态",
    scopePrefixes: ["src/pages/"],
    pattern: /\b(?:toSyntheticSnapshotFromFreshness|groupDatasetSummariesWithFreshnessFallback|inferSourceFromTargetTable|fallbackTs|fallbackStatus)\b/g,
    allowlist: [],
  },
  {
    id: "no-ops-page-derived-raw-table-label",
    description: "禁止页面层自行拼装 raw 表名展示字段",
    scopePrefixes: ["src/pages/"],
    pattern: /\b(?:fallbackRawTable|sourceScopedRawTable)\b/g,
    allowlist: [],
  },
];

function shouldScanFile(relativePath) {
  if (!relativePath.startsWith("src/")) {
    return false;
  }
  if (ignoredFilePatterns.some((pattern) => pattern.test(relativePath))) {
    return false;
  }
  return runtimeExtensions.has(path.extname(relativePath));
}

async function collectFiles(rootDir, baseDir = rootDir) {
  const entries = await readdir(rootDir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const absolutePath = path.join(rootDir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await collectFiles(absolutePath, baseDir)));
      continue;
    }
    if (!entry.isFile()) {
      continue;
    }
    const relativePath = path.relative(baseDir, absolutePath).replaceAll(path.sep, "/");
    if (shouldScanFile(relativePath)) {
      files.push(relativePath);
    }
  }

  return files.sort();
}

function collectMatches(content, pattern) {
  const matches = [];
  const lines = content.split(/\r?\n/);

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    pattern.lastIndex = 0;
    if (pattern.test(line)) {
      matches.push({
        lineNumber: index + 1,
        line: line.trim(),
      });
    }
  }

  return matches;
}

async function main() {
  const files = await collectFiles(srcRoot, frontendRoot);
  const allowlistUsage = [];
  const violations = [];

  for (const relativePath of files) {
    const absolutePath = path.join(frontendRoot, relativePath);
    const content = await readFile(absolutePath, "utf8");

    for (const rule of rules) {
      if (!rule.scopePrefixes.some((prefix) => relativePath.startsWith(prefix))) {
        continue;
      }

      const matches = collectMatches(content, rule.pattern);
      if (!matches.length) {
        continue;
      }

      if (rule.allowlist.includes(relativePath)) {
        allowlistUsage.push({
          ruleId: rule.id,
          file: relativePath,
          count: matches.length,
        });
        continue;
      }

      for (const match of matches) {
        violations.push({
          ruleId: rule.id,
          description: rule.description,
          file: relativePath,
          lineNumber: match.lineNumber,
          line: match.line,
        });
      }
    }
  }

  if (allowlistUsage.length) {
    console.log("Allowed legacy hits:");
    for (const item of allowlistUsage) {
      console.log(`- ${item.ruleId}: ${item.file} (${item.count})`);
    }
    console.log("");
  }

  if (violations.length) {
    console.error("Frontend rule check failed.");
    console.error("");
    for (const item of violations) {
      console.error(`[${item.ruleId}] ${item.description}`);
      console.error(`  ${item.file}:${item.lineNumber}`);
      console.error(`  ${item.line}`);
      console.error("");
    }
    process.exitCode = 1;
    return;
  }

  console.log("Frontend rule check passed.");
}

await main();
