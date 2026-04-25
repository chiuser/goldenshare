export function inferManualTaskSpecType(specKey: string | null | undefined): string | null {
  if (!specKey) {
    return null;
  }
  return specKey.endsWith(".maintain") ? "dataset_action" : "job";
}

export function buildManualTaskHref(input: {
  specKey?: string | null;
  specType?: string | null;
  fromExecutionId?: string | number | null;
  fromScheduleId?: string | number | null;
}): string {
  const search = new URLSearchParams();
  search.set("tab", "manual");
  if (input.specKey) {
    search.set("spec_key", input.specKey);
    search.set("spec_type", input.specType || inferManualTaskSpecType(input.specKey) || "job");
  }
  if (input.fromExecutionId !== undefined && input.fromExecutionId !== null && input.fromExecutionId !== "") {
    search.set("from_execution_id", String(input.fromExecutionId));
  }
  if (input.fromScheduleId !== undefined && input.fromScheduleId !== null && input.fromScheduleId !== "") {
    search.set("from_schedule_id", String(input.fromScheduleId));
  }
  return `/app/ops/v21/datasets/tasks?${search.toString()}`;
}
