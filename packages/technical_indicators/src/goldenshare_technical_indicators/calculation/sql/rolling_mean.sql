CREATE TEMP TABLE {{output}} AS
WITH w AS (
    SELECT seq, count(*) OVER z AS observations, avg(close) OVER z AS mean
    FROM {{price}}
    WINDOW z AS (ORDER BY seq ROWS BETWEEN {{window_preceding}} PRECEDING AND CURRENT ROW)
)
SELECT seq, CASE WHEN observations = ? THEN mean ELSE NULL END::DOUBLE AS value
FROM w WHERE seq >= ? AND seq <= ?;
