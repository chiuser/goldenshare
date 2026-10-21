from decimal import Decimal

import pytest

from orchestrator.tushare_download import DownloadError, DownloadErrorCode
from orchestrator.tushare_download.http_transport import encode_request


def test_json_request_keeps_decimal_as_exact_number_and_boolean_before_integer():
    assert (
        encode_request(
            {
                "value": Decimal("-1.234567890123456789"),
                "flag": True,
                "count": 1,
                "text": "中文",
                "empty": None,
            },
            1024,
        )
        == b'{"value":-1.234567890123456789,"flag":true,"count":1,"text":"\xe4\xb8\xad\xe6\x96\x87","empty":null}'
    )


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), Decimal("NaN"), object()]
)
def test_no_implicit_float_or_arbitrary_object_request_encoding(value):
    with pytest.raises(DownloadError) as caught:
        encode_request({"value": value}, 1024)
    assert caught.value.code == DownloadErrorCode.INPUT


def test_request_capacity_does_not_truncate_parameter_value():
    with pytest.raises(DownloadError) as caught:
        encode_request({"value": "X" * 100}, 16)
    assert caught.value.code == DownloadErrorCode.CAPACITY
