"""Send a single already-encoded response; never own an admission lease."""

from time import monotonic

import anyio
from starlette.types import Send

from src.foundation.technical_indicators.errors import CalculationDeadlineError
from src.foundation.technical_indicators.execution_control import ExecutionControl


async def send_encoded_body(body: bytes, *, send: Send, control: ExecutionControl) -> None:
    control.check_active()
    remaining = control.target_finish - monotonic()
    if remaining <= 0:
        raise CalculationDeadlineError("The response completion deadline was reached")
    with anyio.CancelScope(deadline=anyio.current_time() + remaining) as scope:
        await send({"type": "http.response.start", "status": 200, "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]})
        await send({"type": "http.response.body", "body": body, "more_body": False})
    if scope.cancel_called or monotonic() >= control.target_finish:
        raise CalculationDeadlineError("The response completion deadline was reached")
