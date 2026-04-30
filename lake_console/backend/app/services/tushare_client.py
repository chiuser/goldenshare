from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class TushareLakeClient:
    def __init__(self, token: str | None) -> None:
        if not token:
            raise RuntimeError("缺少 TUSHARE_TOKEN，无法请求 Tushare。")
        try:
            import tushare as ts
        except ModuleNotFoundError as exc:
            raise RuntimeError("缺少 tushare 依赖。请先安装 lake_console/backend/requirements.txt。") from exc
        self._pro = ts.pro_api(token)

    def stock_basic(self, *, list_status: str, fields: Sequence[str]) -> list[dict[str, Any]]:
        frame = self._pro.stock_basic(
            exchange="",
            list_status=list_status,
            fields=",".join(fields),
        )
        return _frame_to_rows(frame)

    def stk_mins(
        self,
        *,
        ts_code: str,
        freq: int,
        start_date: str,
        end_date: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        frame = self._pro.stk_mins(
            ts_code=ts_code,
            freq=f"{freq}min",
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
        return _frame_to_rows(frame)


def _frame_to_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    try:
        return [dict(row) for row in frame.to_dict(orient="records")]
    except AttributeError as exc:
        raise RuntimeError("Tushare 返回值不是可转换的 DataFrame。") from exc
