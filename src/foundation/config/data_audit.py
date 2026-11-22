def data_audit_enabled(settings) -> bool:
    return (
        settings.app_env.strip().lower() in {"dev", "local"}
        and settings.wealth_local_data_audit_enabled
    )
