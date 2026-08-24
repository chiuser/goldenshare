from __future__ import annotations

import logging
import re
from typing import cast

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.news.news_reader_query_service import (
    NewsReaderNotFoundError,
    NewsReaderQueryService,
)
from src.biz.schemas.wealth.market.news_common import NewsContentSourceValue
from src.biz.schemas.wealth.market.news_reader import NewsReaderItemDto
from src.biz.services.wealth.market.news.news_reader_content_resolver import (
    NewsReaderContentInvalidError,
    NewsReaderContentTooLargeError,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wealth/market/news", tags=["wealth-market"])


@router.get("/items/{content_source}/{news_id}", response_model=NewsReaderItemDto)
def get_news_reader_item(
    content_source: str,
    news_id: str,
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> NewsReaderItemDto:
    normalized_content_source = content_source.strip()
    normalized_news_id = news_id.strip()
    if normalized_content_source not in {"news", "major_news"}:
        raise WebAppError(status_code=400, code="NEWS_READER_REQUEST_INVALID", message="新闻来源无效")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", normalized_news_id):
        raise WebAppError(status_code=400, code="NEWS_READER_REQUEST_INVALID", message="新闻标识无效")

    try:
        return NewsReaderQueryService().build_news_reader_item(
            session,
            content_source=cast(NewsContentSourceValue, normalized_content_source),
            news_id=normalized_news_id,
        )
    except NewsReaderNotFoundError as exc:
        raise WebAppError(
            status_code=404,
            code="NEWS_READER_NOT_FOUND",
            message="新闻内容暂不可读",
        ) from exc
    except NewsReaderContentTooLargeError as exc:
        raise WebAppError(
            status_code=413,
            code="NEWS_READER_CONTENT_TOO_LARGE",
            message="新闻内容过大，无法安全展示",
        ) from exc
    except NewsReaderContentInvalidError as exc:
        raise WebAppError(
            status_code=422,
            code="NEWS_READER_CONTENT_INVALID",
            message="新闻内容无法安全展示",
        ) from exc
    except WebAppError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "news reader query failed",
            extra={"content_source": normalized_content_source, "news_id": normalized_news_id},
        )
        raise WebAppError(
            status_code=500,
            code="NEWS_READER_QUERY_FAILED",
            message="新闻内容加载失败",
        ) from exc
