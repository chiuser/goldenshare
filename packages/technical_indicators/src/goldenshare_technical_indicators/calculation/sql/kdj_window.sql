CREATE TEMP TABLE {{output}} AS
WITH w AS (
    SELECT seq, close, max(high) OVER z AS highest, min(low) OVER z AS lowest
    FROM {{price}}
    WINDOW z AS (ORDER BY seq ROWS BETWEEN {{window_preceding}} PRECEDING AND CURRENT ROW)
)
SELECT seq, CASE WHEN highest = lowest THEN 50.0
                ELSE (close - lowest) / (highest - lowest) * 100.0 END::DOUBLE AS rsv
FROM w WHERE seq >= ? AND seq <= ?;
