from __future__ import annotations

import hashlib
import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_top_list_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    normalized = unicodedata.normalize("NFKC", reason)
    normalized = _WHITESPACE_RE.sub(" ", normalized.strip())
    return normalized or None


def hash_top_list_reason(reason: str | None) -> str | None:
    normalized = normalize_top_list_reason(reason)
    if normalized is None:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
