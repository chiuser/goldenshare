from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest
from fastapi.responses import StreamingResponse

from src.app.exceptions import WebAppError
from src.ops.api import schedules as schedules_api


def test_stream_session_factory_creates_independent_sessions_from_request_bind() -> None:
    request_session = Mock()
    bind = Mock()
    request_session.get_bind.return_value = bind

    session_factory = schedules_api._build_stream_session_factory(request_session)
    first_session = session_factory()
    second_session = session_factory()

    try:
        request_session.get_bind.assert_called_once_with()
        assert first_session is not request_session
        assert second_session is not request_session
        assert first_session is not second_session
        assert first_session.get_bind() is bind
        assert second_session.get_bind() is bind
    finally:
        first_session.close()
        second_session.close()


def test_schedule_stream_ends_authentication_transaction_before_streaming(mocker) -> None:
    request_session = Mock()
    stream_session_factory = Mock()
    require_admin = mocker.patch.object(
        schedules_api,
        "_require_admin_from_stream_token",
    )
    build_factory = mocker.patch.object(
        schedules_api,
        "_build_stream_session_factory",
        return_value=stream_session_factory,
    )

    response = schedules_api.stream_ops_schedules(
        token="stream-token",
        session=request_session,
    )

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
    require_admin.assert_called_once_with(request_session, "stream-token")
    build_factory.assert_called_once_with(request_session)
    request_session.rollback.assert_called_once_with()


def test_schedule_stream_rolls_back_failed_authentication_transaction(mocker) -> None:
    request_session = Mock()
    mocker.patch.object(
        schedules_api,
        "_require_admin_from_stream_token",
        side_effect=WebAppError(
            status_code=401,
            code="unauthorized",
            message="登录已失效",
        ),
    )
    build_factory = mocker.patch.object(
        schedules_api,
        "_build_stream_session_factory",
    )

    with pytest.raises(WebAppError, match="登录已失效"):
        schedules_api.stream_ops_schedules(
            token="stream-token",
            session=request_session,
        )

    request_session.rollback.assert_called_once_with()
    build_factory.assert_not_called()


def test_schedule_signature_read_rolls_back_and_closes_before_returning(mocker) -> None:
    first_context = MagicMock()
    second_context = MagicMock()
    first_session = Mock()
    second_session = Mock()
    first_context.__enter__.return_value = first_session
    second_context.__enter__.return_value = second_session
    session_factory = Mock(side_effect=(first_context, second_context))
    signatures = (
        {
            "schedule_updated_at": "2026-08-26T01:00:00+08:00",
            "task_run_requested_at": None,
            "active_task_runs": 0,
        },
        {
            "schedule_updated_at": "2026-08-26T01:00:02+08:00",
            "task_run_requested_at": None,
            "active_task_runs": 0,
        },
    )
    read_signature = mocker.patch.object(
        schedules_api,
        "_schedule_signature",
        side_effect=signatures,
    )

    assert schedules_api._read_schedule_signature(session_factory) == signatures[0]
    first_session.rollback.assert_called_once_with()
    first_context.__exit__.assert_called_once()

    assert schedules_api._read_schedule_signature(session_factory) == signatures[1]
    second_session.rollback.assert_called_once_with()
    second_context.__exit__.assert_called_once()
    assert session_factory.call_count == 2
    assert read_signature.call_args_list[0].args == (first_session,)
    assert read_signature.call_args_list[1].args == (second_session,)


def test_schedule_signature_read_rolls_back_and_closes_on_query_failure(mocker) -> None:
    session_context = MagicMock()
    read_session = Mock()
    session_context.__enter__.return_value = read_session
    session_factory = Mock(return_value=session_context)
    mocker.patch.object(
        schedules_api,
        "_schedule_signature",
        side_effect=RuntimeError("query failed"),
    )

    with pytest.raises(RuntimeError, match="query failed"):
        schedules_api._read_schedule_signature(session_factory)

    read_session.rollback.assert_called_once_with()
    session_context.__exit__.assert_called_once()


def test_schedule_event_stream_preserves_event_and_ping_contract(mocker) -> None:
    signature = {
        "schedule_updated_at": "2026-08-26T01:00:00+08:00",
        "task_run_requested_at": None,
        "active_task_runs": 0,
    }
    session_factory = Mock()
    read_signature = mocker.patch.object(
        schedules_api,
        "_read_schedule_signature",
        side_effect=(signature, signature),
    )
    sleep = mocker.patch.object(schedules_api.time, "sleep")
    events = schedules_api._schedule_event_stream(session_factory)

    first_event = next(events)
    second_event = next(events)

    assert first_event.startswith("event: schedules\ndata: ")
    assert '"active_task_runs": 0' in first_event
    assert first_event.endswith("\n\n")
    assert second_event == ": ping\n\n"
    assert read_signature.call_args_list[0].args == (session_factory,)
    assert read_signature.call_args_list[1].args == (session_factory,)
    sleep.assert_called_once_with(2)
