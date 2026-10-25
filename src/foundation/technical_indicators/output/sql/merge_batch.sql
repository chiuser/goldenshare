CREATE TEMP TABLE {{output}} AS
SELECT /* projection */
FROM {{price}} AS p
/* joins */
WHERE p.seq BETWEEN ? AND ?;
