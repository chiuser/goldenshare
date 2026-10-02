"""Business receipts only; caller controls short transaction boundaries."""
from uuid import UUID
from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert
from src.foundation.models.raw.anns_d_sync import AnnsDSyncUnit, AnnsDSyncRequestBudget
from src.foundation.datasets.anns_d_contracts import AnnouncementPersistenceError


class AnnsDSyncDAO:
    def __init__(self, session, context):
        self.session = session
        self.key = dict(execution_token=UUID(context['execution_token']),
                        contract_digest=context['contract_digest'], scope_hash=context['scope_hash'])

    def receipt(self, day):
        return self.session.execute(select(AnnsDSyncUnit.__table__).filter_by(**self.key, ann_date=day)).mappings().first()

    def complete(self, **values):
        self.session.execute(insert(AnnsDSyncUnit).values(**self.key, **values))

    def issued_requests(self):
        return self.session.execute(select(AnnsDSyncRequestBudget.issued_requests).where(
            AnnsDSyncRequestBudget.execution_token == self.key['execution_token'])).scalar() or 0

    def reserve_request(self, maximum):
        table = AnnsDSyncRequestBudget
        self.session.execute(insert(table).values(**self.key, issued_requests=0).on_conflict_do_nothing())
        row = self.session.execute(select(table.__table__).where(table.execution_token == self.key['execution_token']).with_for_update()).mappings().one()
        if any(row[k] != self.key[k] for k in ('contract_digest', 'scope_hash')):
            raise AnnouncementPersistenceError('anns_d.resume_contract_mismatch', '业务请求预算合同不一致')
        if row['issued_requests'] >= maximum:
            raise AnnouncementPersistenceError('anns_d.request_budget_exceeded', '公告执行真实请求预算已用完')
        value = row['issued_requests'] + 1
        self.session.execute(update(table).where(table.execution_token == self.key['execution_token']).values(issued_requests=value, updated_at=func.now()))
        return value
