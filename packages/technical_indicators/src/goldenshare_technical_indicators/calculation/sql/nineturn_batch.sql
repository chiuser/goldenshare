CREATE TEMP TABLE {{output}} AS
WITH with_comparison AS (
    SELECT seq, close, lag(close, 4) OVER (ORDER BY seq) AS comparison_close
    FROM {{price}}
), directions AS (
    SELECT seq, CASE
        WHEN close > comparison_close THEN 1
        WHEN close < comparison_close THEN -1
        ELSE 0
    END AS bar_direction
    FROM with_comparison
    WHERE seq BETWEEN ? AND ?
), with_previous_direction AS (
    SELECT *, lag(bar_direction) OVER (ORDER BY seq) AS previous_direction
    FROM directions
), segments AS (
    SELECT *, sum(CASE
        WHEN bar_direction = 0 OR bar_direction IS DISTINCT FROM previous_direction THEN 1
        ELSE 0
    END) OVER (ORDER BY seq ROWS UNBOUNDED PRECEDING) AS segment_id
    FROM with_previous_direction
), counts AS (
    SELECT seq, bar_direction, least(
        row_number() OVER (PARTITION BY segment_id ORDER BY seq)
        + CASE WHEN segment_id = 1 AND bar_direction = state.direction THEN state.count ELSE 0 END,
        13
    ) AS run_count
    FROM segments CROSS JOIN {{state}} AS state
)
SELECT seq,
    CASE WHEN bar_direction = 1 THEN run_count ELSE 0 END::DOUBLE AS up_count,
    CASE WHEN bar_direction = -1 THEN run_count ELSE 0 END::DOUBLE AS down_count
FROM counts;
