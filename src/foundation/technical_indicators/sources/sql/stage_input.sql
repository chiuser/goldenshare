CREATE TEMP TABLE {output_table} AS
SELECT row_number() OVER (ORDER BY {time_key}) + ? AS seq, p.*
FROM (SELECT {projection} FROM {registration} b) p
ORDER BY {time_key}
