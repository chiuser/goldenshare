"""Shared set-based nine-turn formula over normalized bar columns."""

from __future__ import annotations

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_COMPARISON_LAG,
    QFQ_NINETURN_SIGNAL_THRESHOLD,
)

NINETURN_FORMULA_INPUT_COLUMNS = (
    "subject_code",
    "bar_date",
    "bar_time",
    "close_value",
)
NINETURN_FORMULA_OUTPUT_COLUMNS = (
    *NINETURN_FORMULA_INPUT_COLUMNS,
    "up_count",
    "down_count",
    "nine_up_turn",
    "nine_down_turn",
)


def build_nineturn_formula_select_sql(
    *,
    source_sql: str,
    context_sql: str | None = None,
    seed_sql: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    target_subject_predicate_sql: str = "true",
) -> str:
    """Build the non-repainting nine-turn projection for normalized bars.

    ``source_sql`` and the optional ``context_sql`` must expose exactly the
    normalized bar semantics ``subject_code, bar_date, bar_time, close_value``.
    ``seed_sql`` must expose ``subject_code, seed_direction, seed_count``.
    Context rows participate only in the lag comparison; the optional date
    window selects rows that are emitted and counted from the supplied seed.
    """

    if (start_date is None) != (end_date is None):
        raise ValueError("Nine-turn start_date and end_date must be provided together.")
    if not target_subject_predicate_sql.strip():
        raise ValueError("Nine-turn target subject predicate cannot be empty.")

    normalized_context_sql = context_sql or _empty_normalized_bar_select()
    normalized_seed_sql = seed_sql or _empty_normalized_seed_select()
    target_date_predicate = "true"
    if start_date is not None and end_date is not None:
        target_date_predicate = (
            f"bar_date BETWEEN DATE {duckdb_string(start_date)} "
            f"AND DATE {duckdb_string(end_date)}"
        )

    return f"""
WITH current_source_rows AS (
  {source_sql}
),
context_rows AS (
  {normalized_context_sql}
),
source_rows AS (
  SELECT subject_code, bar_date, bar_time, close_value FROM context_rows
  UNION ALL
  SELECT subject_code, bar_date, bar_time, close_value FROM current_source_rows
),
lagged_rows AS (
  SELECT
    *,
    LAG(close_value, {QFQ_NINETURN_COMPARISON_LAG}) OVER (
      PARTITION BY subject_code
      ORDER BY bar_time
    ) AS comparison_close
  FROM source_rows
),
target_directions AS (
  SELECT
    *,
    CASE
      WHEN comparison_close IS NULL THEN 0
      WHEN close_value > comparison_close THEN 1
      WHEN close_value < comparison_close THEN -1
      ELSE 0
    END AS direction
  FROM lagged_rows
  WHERE {target_date_predicate}
    AND ({target_subject_predicate_sql})
),
target_segment_flags AS (
  SELECT
    *,
    CASE
      WHEN ROW_NUMBER() OVER (
        PARTITION BY subject_code
        ORDER BY bar_time
      ) = 1 THEN 1
      WHEN direction = 0 THEN 1
      WHEN direction != LAG(direction) OVER (
        PARTITION BY subject_code
        ORDER BY bar_time
      ) THEN 1
      ELSE 0
    END AS segment_start
  FROM target_directions
),
target_segments AS (
  SELECT
    *,
    SUM(segment_start) OVER (
      PARTITION BY subject_code
      ORDER BY bar_time
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS segment_id
  FROM target_segment_flags
),
target_local_counts AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY subject_code, segment_id
      ORDER BY bar_time
    ) AS local_count
  FROM target_segments
),
previous_seeds AS (
  {normalized_seed_sql}
),
continued_rows AS (
  SELECT
    target_local_counts.*,
    CASE
      WHEN target_local_counts.direction = 0 THEN 0
      WHEN target_local_counts.segment_id = 1
       AND target_local_counts.direction = coalesce(previous_seeds.seed_direction, 0)
      THEN coalesce(previous_seeds.seed_count, 0) + target_local_counts.local_count
      ELSE target_local_counts.local_count
    END AS continued_count
  FROM target_local_counts
  LEFT JOIN previous_seeds USING (subject_code)
),
counted_rows AS (
  SELECT
    *,
    CAST(CASE WHEN direction = 1 THEN continued_count ELSE 0 END AS INTEGER)
      AS up_count,
    CAST(CASE WHEN direction = -1 THEN continued_count ELSE 0 END AS INTEGER)
      AS down_count
  FROM continued_rows
),
nineturn_rows AS (
  SELECT
    *,
    CAST(
      CASE WHEN up_count >= {QFQ_NINETURN_SIGNAL_THRESHOLD} THEN '+9' END
      AS VARCHAR
    ) AS nine_up_turn,
    CAST(
      CASE WHEN down_count >= {QFQ_NINETURN_SIGNAL_THRESHOLD} THEN '-9' END
      AS VARCHAR
    ) AS nine_down_turn
  FROM counted_rows
)
SELECT
  subject_code,
  bar_date,
  bar_time,
  close_value,
  up_count,
  down_count,
  nine_up_turn,
  nine_down_turn
FROM nineturn_rows
"""


def _empty_normalized_bar_select() -> str:
    return """
    SELECT
      NULL::VARCHAR AS subject_code,
      NULL::DATE AS bar_date,
      NULL::TIMESTAMP AS bar_time,
      NULL::DOUBLE AS close_value
    WHERE false
    """


def _empty_normalized_seed_select() -> str:
    return """
    SELECT
      NULL::VARCHAR AS subject_code,
      NULL::INTEGER AS seed_direction,
      NULL::INTEGER AS seed_count
    WHERE false
    """


__all__ = [
    "NINETURN_FORMULA_INPUT_COLUMNS",
    "NINETURN_FORMULA_OUTPUT_COLUMNS",
    "build_nineturn_formula_select_sql",
]
