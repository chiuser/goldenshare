"""Append/read business facts. Transactions and publication belong to ingestion."""

from uuid import UUID

from sqlalchemy import func, select

from src.foundation.datasets.stock_period_adj_contracts import StockPeriodAdjContractError, canonical_json, check_size
from src.foundation.models.core.stock_period_adj_delivery import StockPeriodAdjDelivery as Delivery


class StockPeriodAdjDeliveryDAO:
    def __init__(self, session):
        self.session = session

    def get(self, batch_id, kind, unit_id):
        return self.session.scalar(select(Delivery).where(Delivery.batch_id == UUID(str(batch_id)),
            Delivery.record_kind == kind, Delivery.unit_id == unit_id).execution_options(populate_existing=True))

    def frozen_intent(self, intent_key):
        return self.session.scalar(select(Delivery).where(Delivery.intent_key == intent_key, Delivery.record_kind == 'plan_frozen'))

    def frozen_history_pair(self, business_date):
        return {row.freq: row for row in self.session.scalars(select(Delivery).where(
            Delivery.purpose == 'factor_history', Delivery.business_date == business_date,
            Delivery.record_kind == 'plan_frozen'))}

    def append(self, values, policy):
        values = {**values, 'batch_id': UUID(str(values['batch_id']))}
        check_size(values['payload'], policy.max_plan_bytes if values['record_kind'] in {'plan_unit', 'plan_frozen'} else policy.max_payload_bytes,
                   'plan_budget_exceeded' if values['record_kind'] in {'plan_unit', 'plan_frozen'} else 'row_budget_exceeded')
        old = self.get(values['batch_id'], values['record_kind'], values['unit_id'])
        if old is not None:
            if any(canonical_json(getattr(old, key)) != canonical_json(value) for key, value in values.items()):
                raise StockPeriodAdjContractError('同一业务记录键对应不同内容', 'resume_contract_mismatch')
            return old
        row = Delivery(**values)
        self.session.add(row)
        self.session.flush()
        return row

    def units(self, batch_id, *, after='', limit=128):
        return list(self.session.scalars(select(Delivery).where(Delivery.batch_id == UUID(str(batch_id)),
            Delivery.record_kind == 'plan_unit', Delivery.unit_id > after).order_by(Delivery.unit_id).limit(limit)))

    def committed(self, batch_id):
        return list(self.session.scalars(select(Delivery).where(Delivery.batch_id == UUID(str(batch_id)),
            Delivery.record_kind == 'unit').order_by(Delivery.unit_id)))

    def complete(self, business_date, freq):
        return self.session.scalar(select(Delivery).where(Delivery.business_date == business_date,
            Delivery.freq == freq, Delivery.purpose == 'current_period', Delivery.record_kind == 'batch_closed')
            .order_by(Delivery.revision.desc()).limit(1))

    def latest_complete_date(self, freq, before):
        return self.session.scalar(select(func.max(Delivery.business_date)).where(Delivery.freq == freq,
            Delivery.purpose == 'current_period', Delivery.record_kind == 'batch_closed', Delivery.business_date <= before))
