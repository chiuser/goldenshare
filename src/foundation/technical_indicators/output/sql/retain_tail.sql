CREATE TEMP TABLE {{next}} AS
WITH selected AS (
    SELECT /* columns */ FROM {{batch}}
    WHERE /* range */
), combined AS (
    /* previous */
    SELECT /* columns */ FROM selected
)
SELECT /* columns */ FROM combined ORDER BY seq DESC LIMIT ?;
