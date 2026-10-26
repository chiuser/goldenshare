-- Only prepared smoothing parameters are read. No price rows or state updates.
CREATE TEMP TABLE {{warmup}} AS
WITH RECURSIVE settings AS (
    SELECT CAST(? AS BIGINT) AS minimum_rows, CAST(? AS DOUBLE) AS error_budget,
           CAST(? AS DOUBLE) AS price_bound, CAST(? AS BIGINT) AS capacity
), limits AS (
    SELECT settings.*, bf, bslow, bg, ag,
           greatest(minimum_rows::DOUBLE,
               CASE WHEN greatest(bf,bslow,bg) = 0 THEN 0.0
                    ELSE ceil(1.0 / -ln(greatest(bf,bslow,bg))) END) AS lower_bound,
           (2 * ceil(log2(capacity::DOUBLE + 1)) + 6)::INTEGER AS iteration_limit
    FROM {{parameters}} CROSS JOIN settings
),
search(phase, lo, hi, candidate, iteration) AS (
    SELECT 'init'::VARCHAR, 0::BIGINT, 0::BIGINT,
           CASE WHEN lower_bound > capacity THEN capacity ELSE lower_bound::BIGINT END,
           0::INTEGER
    FROM limits
    UNION ALL
    SELECT transition.next_phase, transition.next_lo, transition.next_hi,
           CASE WHEN transition.next_phase = 'double'
                    THEN least(capacity::HUGEINT, transition.next_lo::HUGEINT * 2)::BIGINT
                WHEN transition.next_phase = 'bisect'
                    THEN transition.next_lo + (transition.next_hi - transition.next_lo) // 2
                ELSE candidate END,
           iteration + 1
    FROM search CROSS JOIN limits
    CROSS JOIN LATERAL (
        SELECT greatest(dif_bound, dea_bound, 2.0 * (dif_bound + dea_bound)) <= error_budget AS passed
        FROM (
            SELECT 2.0 * price_bound * (pow(bf,candidate) + pow(bslow,candidate)) AS dif_bound,
                   2.0 * price_bound * (pow(bg,candidate) + ag * (uf + us)) AS dea_bound
            FROM (
                SELECT CASE WHEN bf = 0 THEN 0.0
                            WHEN bf = bg THEN candidate * pow(bf,candidate)
                            ELSE pow(greatest(bf,bg),candidate)
                                * least(candidate::DOUBLE, bf / abs(bf-bg)) END AS uf,
                       CASE WHEN bslow = 0 THEN 0.0
                            WHEN bslow = bg THEN candidate * pow(bslow,candidate)
                            ELSE pow(greatest(bslow,bg),candidate)
                                * least(candidate::DOUBLE, bslow / abs(bslow-bg)) END AS us
            ) u
        ) bounds
    ) evaluated
    CROSS JOIN LATERAL (
        SELECT CASE
            WHEN phase = 'init' THEN CASE
                WHEN lower_bound > capacity OR passed THEN 'done' ELSE 'double' END
            WHEN phase = 'double' THEN CASE
                WHEN passed THEN CASE WHEN candidate - lo <= 1 THEN 'done' ELSE 'bisect' END
                WHEN candidate = capacity THEN 'done' ELSE 'double' END
            ELSE CASE WHEN passed THEN
                CASE WHEN candidate - lo <= 1 THEN 'done' ELSE 'bisect' END
                ELSE CASE WHEN hi - candidate <= 1 THEN 'done' ELSE 'bisect' END END
            END AS next_phase,
            CASE WHEN phase = 'init' AND NOT passed THEN candidate
                 WHEN phase IN ('double', 'bisect') AND NOT passed THEN candidate
                 ELSE lo END AS next_lo,
            CASE WHEN phase = 'init' AND lower_bound <= capacity AND passed THEN candidate
                 WHEN phase IN ('double', 'bisect') AND passed THEN candidate
                 ELSE hi END AS next_hi
    ) transition
    WHERE phase <> 'done' AND iteration < iteration_limit
), final AS (
    SELECT phase, hi FROM search ORDER BY iteration DESC LIMIT 1
)
SELECT CASE WHEN phase <> 'done' THEN error('warmup_search_not_terminated')
            WHEN lower_bound > capacity OR hi = 0 THEN NULL
            ELSE hi END::BIGINT AS warmup_rows,
       (lower_bound > capacity OR hi = 0)::BOOLEAN AS requires_source_origin
FROM final CROSS JOIN limits;
