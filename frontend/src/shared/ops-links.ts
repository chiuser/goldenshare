export function buildDatasetCardPageHref(sourceKey: string | null | undefined): string {
  if (!sourceKey) {
    return "/app/ops/v21/overview";
  }
  return sourceKey === "biying"
    ? "/app/ops/v21/datasets/biying"
    : "/app/ops/v21/datasets/tushare";
}

export function buildManualTaskHref(input: {
  actionKey?: string | null;
  actionType?: string | null;
  fromTaskRunId?: string | number | null;
  fromScheduleId?: string | number | null;
}): string {
  const search = new URLSearchParams();
  search.set("tab", "manual");
  if (input.actionKey) {
    search.set("action_key", input.actionKey);
    if (input.actionType) {
      search.set("action_type", input.actionType);
    }
  }
  if (input.fromTaskRunId !== undefined && input.fromTaskRunId !== null && input.fromTaskRunId !== "") {
    search.set("from_task_run_id", String(input.fromTaskRunId));
  }
  if (input.fromScheduleId !== undefined && input.fromScheduleId !== null && input.fromScheduleId !== "") {
    search.set("from_schedule_id", String(input.fromScheduleId));
  }
  return `/app/ops/v21/datasets/tasks?${search.toString()}`;
}
