INSERT INTO {{state}}
SELECT seq, high, low, high, low FROM {{price}} WHERE seq = ?;
