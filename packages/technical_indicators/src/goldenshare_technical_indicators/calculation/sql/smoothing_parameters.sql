WITH p AS (
    SELECT CAST(? AS BIGINT) AS n, CAST(? AS VARCHAR) AS kind
), a AS (
    SELECT *, CASE WHEN kind = 'ema' THEN 2.0 / (CAST(n AS DOUBLE) + 1.0)
                   ELSE 1.0 / CAST(n AS DOUBLE) END AS alpha
    FROM p
)
SELECT n, alpha, 1.0 - alpha AS beta,
       CASE WHEN n = 1 THEN 1024
            WHEN alpha <= 0 OR NOT isfinite(alpha)
                 OR NOT (1.0 - alpha > 0 AND 1.0 - alpha < 1) THEN NULL
            ELSE least(1024, greatest(1, floor(256.0 / (-ln(1.0 - alpha)))))::INTEGER
       END AS safe_rows
FROM a;
