from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app/auth split phase 1 migrated main implementation to src.app.auth.security_utils.
from src.app.auth.security_utils import generate_raw_token, hash_raw_token, normalize_email, normalize_username

__all__ = ["generate_raw_token", "hash_raw_token", "normalize_username", "normalize_email"]
