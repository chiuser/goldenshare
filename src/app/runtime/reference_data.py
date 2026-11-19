from pathlib import Path

from src.foundation.clients.local_lake.reference_data_reader import (
    LakeSecurityReferenceReader,
    LakeTradeCalendarReader,
)
from src.foundation.clients.reference_data import ReferenceData
from src.foundation.config.settings import Settings


def build_reference_data(settings: Settings) -> ReferenceData | None:
    local = (
        "app_env" in settings.model_fields_set
        and settings.app_env.strip().lower() in {"dev", "local"}
    )
    if not local:
        return None
    configured_root = settings.goldenshare_lake_root.strip()
    root = Path(configured_root).expanduser() if configured_root else None
    return ReferenceData(
        LakeTradeCalendarReader(root), LakeSecurityReferenceReader(root)
    )
