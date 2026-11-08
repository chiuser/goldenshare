CREATE TEMP TABLE {{output}} AS
WITH w AS (
    SELECT seq, count(*) OVER z AS observations, stddev_pop(close) OVER z AS deviation
    FROM {{price}}
    WINDOW z AS (ORDER BY seq ROWS BETWEEN {{window_preceding}} PRECEDING AND CURRENT ROW)
), ready AS (
    SELECT w.seq, m.value AS mean,
           CASE WHEN w.observations = ? THEN w.deviation ELSE NULL END AS deviation
    FROM w JOIN {{mean}} m ON m.seq = w.seq
    WHERE w.seq >= ? AND w.seq <= ?
)
SELECT seq, mean::DOUBLE AS middle,
       (mean + ? * deviation)::DOUBLE AS upper,
       (mean - ? * deviation)::DOUBLE AS lower
FROM ready;
