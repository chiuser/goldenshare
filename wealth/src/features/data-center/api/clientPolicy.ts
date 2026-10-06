/** Fixed observer protocol, approved in LLD §5/9; not user/deployment settings.
 * Cross-language contract tests check these budgets against DataCenterPolicy.
 * Display defaults (dates, interval, polling) are supplied by the context API.
 */
export const clientPolicy = {
  requestSeconds: 5,
  readRetrySeconds: 5,
  staleSeconds: 15,
  defaultPollSeconds: 2,
  companyDebounceMs: 300,
  companyLimit: 20,
  companyKeywordLimit: 64,
  titleLimit: 200,
  historyLimit: 20,
  resultLimit: 50,
} as const;
