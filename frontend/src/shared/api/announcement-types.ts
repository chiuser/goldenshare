export interface AnnouncementProgress {
  phase: "planning" | "fetching" | "persisting" | "reconciling" | "completed" | "canceled" | "failed";
  ann_date: string | null;
  page_number: number;
  offset: number;
  unit_done: number;
  unit_total: number;
  issued_requests: number;
  updated_at: string | null;
  counters: Record<string, number>;
  quality_counts: Record<string, number>;
}
