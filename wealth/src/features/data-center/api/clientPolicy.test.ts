import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { clientPolicy } from "./clientPolicy";
it("fixed client budgets match the single backend policy contract", () => {
  const policy = readFileSync(resolve(process.cwd(), "../src/foundation/config/announcement_archive.py"), "utf8");
  const pairs = { api_seconds: clientPolicy.requestSeconds, stale_seconds: clientPolicy.staleSeconds,
    poll_seconds: clientPolicy.defaultPollSeconds, company_limit: clientPolicy.companyLimit,
    keyword_limit: clientPolicy.companyKeywordLimit, title_limit: clientPolicy.titleLimit,
    history_size: clientPolicy.historyLimit, result_size: clientPolicy.resultLimit };
  for (const [name, value] of Object.entries(pairs)) {
    const declared = policy.match(new RegExp(`^    ${name}: (?:int|float) = ([0-9.]+)$`, "m"));
    expect(declared, name).not.toBeNull(); expect(Number(declared![1]), name).toBe(value);
  }
});
