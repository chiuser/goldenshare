from src.foundation.config.settings import Settings


def etf_activity_enabled(settings: Settings) -> bool:
    """The ETF module is only mounted when the local environment is explicit."""
    return (
        "app_env" in settings.model_fields_set
        and settings.app_env.strip().lower() in {"dev", "local"}
    )
