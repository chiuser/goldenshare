CREATE TEMP TABLE {{work}} AS
WITH x AS (
    SELECT v.seq, v.seq - s.last_seq AS j, v.rsv, p.*, s.k AS seed_k, s.d AS seed_d
    FROM {{range}} v CROSS JOIN {{state}} s CROSS JOIN {{parameters}} p
    WHERE v.seq > s.last_seq AND v.seq <= ?
), k_values AS (
    SELECT *, CASE WHEN k_period = 1 THEN rsv ELSE power(bk, j) * seed_k
        + ak * power(bk, j) * fsum(rsv * power(CASE WHEN k_period = 1 THEN 1.0 ELSE bk END, -j))
          OVER (ORDER BY j ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) END AS next_k
    FROM x
), d_values AS (
    SELECT *, CASE WHEN d_period = 1 THEN next_k ELSE power(bd, j) * seed_d
        + ad * power(bd, j) * fsum(next_k * power(CASE WHEN d_period = 1 THEN 1.0 ELSE bd END, -j))
          OVER (ORDER BY j ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) END AS next_d
    FROM k_values
)
SELECT seq, next_k AS k, next_d AS d, 3.0 * next_k - 2.0 * next_d AS j FROM d_values;
