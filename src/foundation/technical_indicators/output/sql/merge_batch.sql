SELECT /* columns */
FROM (
  SELECT /* projection */
  FROM {{price}} AS p
  /* joins */
  WHERE p.seq BETWEEN ? AND ?
) AS selected
WHERE /* range */;
