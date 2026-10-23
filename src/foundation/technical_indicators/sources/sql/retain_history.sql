CREATE TEMP TABLE {output_table} AS
SELECT * FROM {input_table} ORDER BY seq DESC LIMIT ?
