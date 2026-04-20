from __future__ import annotations

from typing import Any

import requests

from src.foundation.services.sync_v2.errors import StructuredError


class SyncV2ErrorMapper:
    def map_exception(self, *, exc: Exception, phase: str, unit_id: str | None = None) -> StructuredError:
        message = str(exc)

        if isinstance(exc, requests.Timeout):
            return StructuredError(
                error_code="source_timeout",
                error_type="source",
                phase=phase,
                message=message,
                retryable=True,
                unit_id=unit_id,
            )
        if isinstance(exc, requests.HTTPError):
            status_code = self._extract_status_code(exc)
            if status_code == 429:
                code = "source_rate_limited"
                retryable = True
            elif status_code is not None and 500 <= status_code <= 599:
                code = "source_server_error"
                retryable = True
            elif status_code in {401, 403}:
                code = "source_auth_error"
                retryable = False
            else:
                code = "source_http_error"
                retryable = status_code is not None and status_code >= 500
            return StructuredError(
                error_code=code,
                error_type="source",
                phase=phase,
                message=message,
                retryable=retryable,
                unit_id=unit_id,
                details={"http_status": status_code},
            )
        if isinstance(exc, ValueError):
            return StructuredError(
                error_code="payload_invalid",
                error_type="normalize",
                phase=phase,
                message=message,
                retryable=False,
                unit_id=unit_id,
            )
        return StructuredError(
            error_code="internal_error",
            error_type="internal",
            phase=phase,
            message=message,
            retryable=False,
            unit_id=unit_id,
        )

    @staticmethod
    def _extract_status_code(exc: requests.HTTPError) -> int | None:
        response: Any = getattr(exc, "response", None)
        if response is None:
            return None
        try:
            return int(response.status_code)
        except Exception:
            return None
