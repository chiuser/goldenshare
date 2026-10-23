CREATE TEMP TABLE {output_table} AS
SELECT {projection}
FROM {input_table} b
LEFT JOIN {factors} f ON f.trade_date = b.trade_date
CROSS JOIN {basis} a
ORDER BY b.seq
