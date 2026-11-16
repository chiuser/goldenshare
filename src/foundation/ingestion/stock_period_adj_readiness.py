"""Three-field source precheck. Period projection remains in the resolver."""

from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.datasets.stock_period_adj_contracts import StockPeriodAdjContractError
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.foundation.ingestion.source_client import DatasetSourceClient
from src.foundation.ingestion.stock_period_adj_execution import PeriodControl, capture


def check_current_period(session, *, dataset_key, business_date, source_client=None):
    definition = get_dataset_definition(dataset_key)
    request = DatasetActionRequest(dataset_key=dataset_key, action='maintain',
        time_input=DatasetTimeInput(mode='point', business_date=business_date),
        maintenance_intent={'kind': 'current_period'}, trigger_source='probe')
    plan = DatasetActionResolver(session).build_plan(request)
    control = PeriodControl(lambda: None, lambda stage, force=True: None)
    try:
        _, counts = capture(SimpleNamespace(source_client=source_client or DatasetSourceClient()),
            definition, plan.units[0], control, readiness=True)
    except StockPeriodAdjContractError as exc:
        if exc.code == 'stock_period_adj.source_not_ready':
            return False, str(exc), {'business_date': business_date.isoformat()}
        raise
    return True, '源当期覆盖和计算截至日期已齐备', {'business_date': business_date.isoformat(), **counts}
