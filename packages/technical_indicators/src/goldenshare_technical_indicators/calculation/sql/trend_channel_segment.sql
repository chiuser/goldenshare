CREATE TEMP TABLE {{work}} AS
WITH x AS (
    SELECT b.seq,b.seq-s.last_seq AS j,b.high,b.low,p.*,
           s.short_upper AS seed_short_upper,s.short_lower AS seed_short_lower,
           s.long_upper AS seed_long_upper,s.long_lower AS seed_long_lower
    FROM {{price}} b CROSS JOIN {{state}} s CROSS JOIN {{parameters}} p
    WHERE b.seq > s.last_seq AND b.seq <= ?
)
SELECT seq,
    power(short_beta,j)*seed_short_upper + short_alpha*power(short_beta,j)
        *fsum(high*power(short_beta,-j)) OVER (ORDER BY j ROWS UNBOUNDED PRECEDING) AS short_upper,
    power(short_beta,j)*seed_short_lower + short_alpha*power(short_beta,j)
        *fsum(low*power(short_beta,-j)) OVER (ORDER BY j ROWS UNBOUNDED PRECEDING) AS short_lower,
    power(long_beta,j)*seed_long_upper + long_alpha*power(long_beta,j)
        *fsum(high*power(long_beta,-j)) OVER (ORDER BY j ROWS UNBOUNDED PRECEDING) AS long_upper,
    power(long_beta,j)*seed_long_lower + long_alpha*power(long_beta,j)
        *fsum(low*power(long_beta,-j)) OVER (ORDER BY j ROWS UNBOUNDED PRECEDING) AS long_lower
FROM x;
