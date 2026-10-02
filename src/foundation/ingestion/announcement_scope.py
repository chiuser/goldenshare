"""Freeze and validate the announcement execution contract without Ops dependencies."""
from dataclasses import asdict
import json
from uuid import UUID, uuid4
from src.foundation.datasets.anns_d_contracts import digest
from src.foundation.ingestion.errors import IngestionPlanningError, StructuredError


def scope_error(message):
    return IngestionPlanningError(StructuredError(error_code='anns_d.resume_contract_mismatch',
        error_type='planning', phase='resolver', message=message, retryable=False))


def freeze_execution(definition, *, scope, filters, previous=None):
    if definition.planning.announcement_policy is None:
        if previous is not None:
            raise scope_error('该数据集不支持公告执行恢复合同')
        return None
    # The contract includes all implementation budgets, source fields and identity semantics.
    snapshot = {'planning': asdict(definition.planning), 'storage': asdict(definition.storage),
                'normalization': asdict(definition.normalization), 'source': asdict(definition.source),
                'date_model': asdict(definition.date_model), 'identity_contract': 'information_dominance_v1'}
    snapshot = json.loads(json.dumps(snapshot))
    contract_digest = digest(snapshot)
    scope_hash = digest({'dataset_key': definition.dataset_key, 'scope': scope, 'filters': filters})
    if previous is not None:
        if not isinstance(previous, dict):
            raise scope_error('缺少冻结执行合同')
        try:
            token = str(UUID(previous['execution_token']))
        except (ValueError, KeyError, TypeError):
            raise scope_error('执行token无效') from None
        if previous.get('contract_digest') != contract_digest or previous.get('scope_hash') != scope_hash or previous.get('policy_snapshot') != snapshot:
            raise scope_error('恢复范围、过滤或合同预算不一致')
    else:
        token = str(uuid4())
    # Snapshot must survive a JSON round trip (tuples -> lists) identically.
    return dict(execution_token=token, contract_digest=contract_digest, scope_hash=scope_hash, policy_snapshot=snapshot)
