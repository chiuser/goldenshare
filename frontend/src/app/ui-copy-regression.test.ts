import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";


const filesToCheck = [
  "src/app/shell.tsx",
  "src/pages/login-page.tsx",
  "src/pages/platform-check-page.tsx",
  "src/pages/ops-today-page.tsx",
  "src/pages/ops-automation-page.tsx",
  "src/pages/ops-manual-sync-page.tsx",
  "src/pages/ops-tasks-page.tsx",
  "src/pages/ops-task-detail-page.tsx",
];

const bannedVisiblePhrases = [
  "Frontend App Foundation",
  "Administrator",
  "Operator",
  "Web Health",
  "Auth Session",
  "App Route",
  "Health 检查失败",
  "Goldenshare Frontend",
  "Job Specs",
  "Workflow Specs",
  "执行参数（JSON）",
  "调度参数（JSON）",
  "重试策略（JSON）",
  "并发策略（JSON）",
  "当前筛选下没有 execution",
  "最近一次 execution 操作",
  "execution 已创建",
  "execution 创建失败",
  "execution 已重试",
  "execution 已请求取消",
  "按 message / payload 过滤",
  "按 job_name / message 过滤",
  "scheduler tick",
  "worker run",
  "execution queue",
];

describe("运维前端文案回归", () => {
  it("关键页面不应回流已知英文用户文案", () => {
    const root = resolve(__dirname, "..", "..");
    for (const file of filesToCheck) {
      const content = readFileSync(resolve(root, file), "utf-8");
      for (const phrase of bannedVisiblePhrases) {
        expect(content).not.toContain(phrase);
      }
    }
  });
});
