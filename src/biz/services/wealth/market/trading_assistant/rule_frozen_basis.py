"""Retain source material once; all later batches read that immutable material."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from uuid import uuid4

from sqlalchemy import select
from src.biz.models.wealth.trading_assistant.rule_checks import RuleMarketBasis
from .market_facts import facts_digest
from .rule_calendar import TIME_LABEL_VERSION, session_minutes
from .rule_minute_batch import MinuteFact, RequiredMinute


def freeze_basis(session, target, *, required, source, session_evidence, now, policy, deadline):
    if source is not None:
        allowed = {m.at for m in session_minutes(target.day)}
        if (source.stock_code != target.stock_code or source.trade_date != target.day
                or any(r.checkpoint_at not in allowed for r in source.rows)):
            raise ValueError("Minute source identity or session differs")
    material = [] if source is None else [[r.checkpoint_at.isoformat(), r.close_text, r.volume_shares_text] for r in source.rows]
    document = dict(material=material, session=session_evidence,
        required=[[r.at.isoformat(), r.is_checkpoint] for r in required])
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(material) > policy.page_rows or len(encoded) > policy.page_bytes:
        raise ValueError("Frozen minute material exceeds the execution budget")
    digest = facts_digest(document)
    existing = session.scalar(select(RuleMarketBasis).where(RuleMarketBasis.owner_user_id == target.owner_id,
        RuleMarketBasis.rule_id == target.rule_id, RuleMarketBasis.trade_date == target.day,
        RuleMarketBasis.source_version == digest).limit(1))
    if existing is not None:
        return existing
    row = RuleMarketBasis(market_basis_id=uuid4(), owner_user_id=target.owner_id, rule_id=target.rule_id,
        stock_code=target.stock_code, trade_date=target.day, source="GOLD_STK_MINS_QFQ" if source else "TRADE_CALENDAR",
        source_version=digest, price_basis="QFQ", time_label_version=TIME_LABEL_VERSION, volume_unit="SHARE",
        session_evidence=session_evidence, coverage=dict(required=document["required"],
            sourceVersion=source.source_version if source else None), observed_at=now, material=material)
    session.add(row)
    session.flush()
    deadline.remaining_ms()
    return row


def read_frozen_minutes(basis, *, after, limit, deadline):
    required = tuple(RequiredMinute(datetime.fromisoformat(at), checkpoint)
        for at, checkpoint in basis.coverage["required"] if after is None or datetime.fromisoformat(at) > after)[:limit]
    expected = {r.at for r in required}
    facts = []
    for at_text, price_text, volume_text in basis.material:
        deadline.remaining_ms()
        at = datetime.fromisoformat(at_text)
        if at not in expected:
            continue
        try:
            price = Decimal(price_text) if price_text is not None else None
        except (InvalidOperation, TypeError):
            price = None
        try:
            volume = Decimal(volume_text) if volume_text is not None else None
            volume = int(volume) if volume is not None and volume.is_finite() and volume >= 0 and volume == volume.to_integral_value() else None
        except (InvalidOperation, TypeError, ValueError):
            volume = None
        facts.append(MinuteFact(at, price, volume))
    return required, tuple(facts)
