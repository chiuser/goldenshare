export interface WeeklyAdjProgress {
  stage: string;
  updated_at: string;
  ts_code?: string | null;
  trade_date?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  unit_done: number;
  unit_total: number;
  page_number: number;
  rows_preserved: number;
  eta: "unavailable";
}
