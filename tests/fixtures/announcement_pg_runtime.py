"""Test-only native PG fact assertions, materialized within a short transaction.

SQL is PostgreSQL at the call site; this helper does not translate SQLite SQL,
provide a connection facade, or participate in application execution.
"""
from sqlalchemy import text


class Fact(dict):
    def __getitem__(self,key):
        return tuple(self.values())[key] if isinstance(key,int) else super().__getitem__(key)


class Facts(list):
    def fetchone(self):return self[0] if self else None
    def fetchmany(self,count):return self[:count]
    @property
    def rowcount(self):return self.count_written


def pg_execute(ledger,sql,params=()):
    values=dict(params) if isinstance(params,dict) else {f'p{i}':v for i,v in enumerate(params)}
    values['a']=ledger.archive_id
    with ledger.database.transaction() as conn:
        result=conn.execute(text(sql),values)
        rows=Facts(Fact(r) for r in result.mappings()) if result.returns_rows else Facts()
        rows.count_written=result.rowcount
        return rows


def pg_many(ledger,sql,rows):
    for row in rows:pg_execute(ledger,sql,row)
