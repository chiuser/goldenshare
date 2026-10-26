-- Window size is bound explicitly; the smoothing table has no window column.
CREATE TEMP TABLE {{warmup}} AS
WITH RECURSIVE settings AS (
    SELECT CAST(? AS BIGINT) AS minimum_rows, CAST(? AS DOUBLE) AS error_budget,
           CAST(? AS BIGINT) AS window_rows, CAST(? AS BIGINT) AS capacity
), limits AS (
    SELECT settings.*, bk, bd, ad,
           CASE WHEN bk = 0 AND bd = 0 THEN window_rows::DOUBLE - 1
                ELSE greatest(minimum_rows::DOUBLE, window_rows::DOUBLE - 1,
                    ceil(1.0 / -ln(greatest(bk,bd))) + window_rows::DOUBLE - 2)
                END AS lower_bound,
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
        SELECT greatest(k_bound, d_bound, 3.0 * k_bound + 2.0 * d_bound) <= error_budget AS passed
        FROM (
            SELECT 100.0 * pow(bk,t) AS k_bound,
                   100.0 * (pow(bd,t) + ad * uk) AS d_bound
            FROM (
                SELECT *, CASE WHEN bk = 0 THEN 0.0
                               WHEN bk = bd THEN t * pow(bk,t)
                               ELSE pow(greatest(bk,bd),t)
                                   * least(t::DOUBLE, bk / abs(bk-bd)) END AS uk
                FROM (SELECT greatest(1.0, candidate::DOUBLE - window_rows::DOUBLE + 2) AS t) exponent
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
            WHEN lower_bound > capacity THEN NULL
            WHEN bk = 0 AND bd = 0 THEN window_rows - 1
            WHEN hi = 0 THEN NULL
            ELSE hi END::BIGINT AS warmup_rows,
       (lower_bound > capacity OR (hi = 0 AND NOT (bk = 0 AND bd = 0)))::BOOLEAN AS requires_source_origin
FROM final CROSS JOIN limits;
