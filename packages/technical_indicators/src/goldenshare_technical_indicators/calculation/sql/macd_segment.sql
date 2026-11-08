CREATE TEMP TABLE {{work}} AS
WITH x AS (
    SELECT b.seq, b.seq - s.last_seq AS j, b.close - s.origin_price AS x, p.*,
           s.ema_fast_offset AS seed_fast, s.ema_slow_offset AS seed_slow, s.dea AS seed_dea
    FROM {{price}} b CROSS JOIN {{state}} s CROSS JOIN {{parameters}} p
    WHERE b.seq > s.last_seq AND b.seq <= ?
), e AS (
    SELECT *,
        CASE WHEN fast = 1 THEN x ELSE power(bf, j) * seed_fast
             + af * power(bf, j) * fsum(x * power(CASE WHEN fast = 1 THEN 1.0 ELSE bf END, -j))
               OVER (ORDER BY j ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) END AS ef,
        CASE WHEN slow = 1 THEN x ELSE power(bslow, j) * seed_slow
             + aslow * power(bslow, j) * fsum(x * power(CASE WHEN slow = 1 THEN 1.0 ELSE bslow END, -j))
               OVER (ORDER BY j ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) END AS es
    FROM x
), d AS (
    SELECT *, ef - es AS dif FROM e
), a AS (
    SELECT *, CASE WHEN signal = 1 THEN dif ELSE power(bg, j) * seed_dea
         + ag * power(bg, j) * fsum(dif * power(CASE WHEN signal = 1 THEN 1.0 ELSE bg END, -j))
           OVER (ORDER BY j ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) END AS next_dea
    FROM d
)
SELECT seq, ef, es, dif, next_dea AS dea, 2.0 * (dif - next_dea) AS hist FROM a;
