export function inferManualTaskSpecType(specKey: string | null | undefined): string | null {
  if (!specKey) {
    return null;
  }
  return specKey.endsWith(".maintain") ? "dataset_action" : "job";
}

export function buildManualTaskHref(input: {
  specKey?: string | null;
  specType?: string | null;
  fromTaskRunId?: string | number | null;
  fromScheduleId?: string | number | null;
}): string {
  const search = new URLSearchParams();
  search.set("tab", "manual");
  if (input.specKey) {
    search.set("spec_key", input.specKey);
    search.set("spec_type", input.specType || inferManualTaskSpecType(input.specKey) || "job");
  }
  if (input.fromTaskRunId !== undefined && input.fromTaskRunId !== null && input.fromTaskRunId !== "") {
    search.set("from_task_run_id", String(input.fromTaskRunId));
  }
  if (input.fromScheduleId !== undefined && input.fromScheduleId !== null && input.fromScheduleId !== "") {
    search.set("from_schedule_id", String(input.fromScheduleId));
  }
  return `/app/ops/v21/datasets/tasks?${search.toString()}`;
}
