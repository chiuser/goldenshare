from __future__ import annotations

from typing import Callable


def fetch_rows_with_pagination(
    *,
    pagination_policy: str,
    page_limit: int | None,
    fetch_page: Callable[[int | None, int | None], tuple[list[dict], int]],
) -> tuple[list[dict], int, int]:
    if pagination_policy != "offset_limit" or page_limit is None:
        rows, retries = fetch_page(None, None)
        return rows, 1, retries

    rows_raw: list[dict] = []
    request_count = 0
    retry_count = 0
    offset = 0
    while True:
        rows, retries = fetch_page(offset, page_limit)
        request_count += 1
        retry_count += retries
        rows_raw.extend(rows)
        if len(rows) < page_limit:
            break
        offset += page_limit
    return rows_raw, request_count, retry_count

