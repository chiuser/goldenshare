"""SQL coverage/chain checks for already-verified, bounded prefix pages."""
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import aliased

from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from .calculation_inputs import CalculationInputMismatch


def verify_prefix_price_proof(session, *, account_id, generation_id, business_date,
                              source_generation_id, manifest_digest, price_origin_id):
    node, previous, source, source_previous = (aliased(CalculationBatch) for _ in range(4))
    scope = (node.account_id == account_id, node.generation_id == generation_id,
        node.trade_date == business_date, node.stage == "PREFIX_PRICE_CHECK", node.stock_key == "")
    after = node.accumulator["afterPage"].astext
    parent_digest = node.accumulator["previousProofDigest"].astext
    parent = select(previous.page_key).where(previous.account_id == account_id,
        previous.generation_id == generation_id, previous.trade_date == business_date,
        previous.stage == "PREFIX_PRICE_CHECK", previous.stock_key == "", previous.page_key == after,
        func.encode(previous.input_digest, "hex") == parent_digest).exists()
    invalid = or_(node.accumulator["sourceGenerationId"].astext.is_distinct_from(str(source_generation_id)),
        node.accumulator["sourceManifestDigest"].astext.is_distinct_from(manifest_digest.hex()),
        node.accumulator["done"].as_boolean().is_distinct_from(node.page_key == "END"),
        node.accumulator["nextPage"].astext.is_distinct_from(case((node.page_key == "END", None), else_=node.page_key)),
        and_(after.is_(None), parent_digest.is_not(None)), and_(after.is_not(None), ~parent),
        node.cursor != {"done": True})
    if price_origin_id is None:
        invalid = or_(invalid, node.page_key != "END", node.row_count != 0, after.is_not(None),
            node.accumulator["sourcePageDigest"].astext.is_not(None))
    else:
        source_scope = (source.account_id == account_id, source.generation_id == price_origin_id,
            source.trade_date == business_date, source.stock_key == "")
        source_match = select(source.page_key).where(*source_scope,
            source.stage == case((node.page_key == "END", "VALUATION_END"), else_="VALUATION"),
            source.page_key == case((node.page_key == "END", "1"), else_=node.page_key),
            source.row_count == node.row_count,
            func.encode(source.input_digest, "hex") == node.accumulator["sourcePageDigest"].astext).exists()
        prior_key = select(func.max(source_previous.page_key)).where(source_previous.account_id == account_id,
            source_previous.generation_id == price_origin_id, source_previous.trade_date == business_date,
            source_previous.stage == "VALUATION", source_previous.stock_key == "",
            or_(node.page_key == "END", source_previous.page_key < node.page_key)).correlate(node).scalar_subquery()
        invalid = or_(invalid, ~source_match, after.is_distinct_from(prior_key))
        checked = select(node.page_key).where(*scope, node.page_key == source.page_key).exists()
        missing = session.scalar(select(source.page_key).where(*source_scope, source.stage == "VALUATION", ~checked).limit(1))
        if missing is not None:
            raise CalculationInputMismatch("Prefix price verification has a missing source page")
    if session.scalar(select(node.page_key).where(*scope, invalid).limit(1)) is not None:
        raise CalculationInputMismatch("Prefix price verification chain differs from actual saved pages")
