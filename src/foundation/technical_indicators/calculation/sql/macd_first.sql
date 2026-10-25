INSERT INTO {{state}}
SELECT b.seq, b.close, 0.0, 0.0, 0.0 FROM {{price}} b WHERE b.seq = ?;
