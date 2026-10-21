from decimal import Decimal

from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download import DownloadTask
from orchestrator.tushare_download.download_models import SourcePage, SourceRecord

from .fixtures import build, contract


def test_stable_ascending_time_invalid_missing_and_null_at_end_without_value_changes():
    fields = ("trade_date", "value")
    # Intentional malformed business times and missing columns are NOT protocol errors.
    records = (
        SourceRecord(fields, ("20180718", Decimal("-1.00")), 0),
        SourceRecord(fields, (None, 7), 0),
        SourceRecord(fields, ("20180717", 2), 0),
        SourceRecord(fields, ("20180717", 3), 0),
        SourceRecord(fields, ("bad", 8), 0),
    )

    def source(request, attempt):
        if dict(request.params)["offset"] == 0:
            return SourcePage(fields, records)
        return SourcePage(("value",), (SourceRecord(("value",), (9,), 0),))

    downloader, _, _, _ = build(source, definition=contract(limit=5))
    with downloader.download(DownloadTask("fixture.daily@1", M.SNAPSHOT)) as session:
        results = list(session)
    result = results[0]
    assert [r.as_mapping()["value"] for r in result.records] == [
        2,
        3,
        Decimal("-1.00"),
        7,
        8,
        9,
    ]
    assert (
        result.ordering.comparable_count == 3
        and result.ordering.uncomparable_count == 3
    )
    assert "trade_date" not in result.records[-1].as_mapping()
    assert result.records[2].values[1].as_tuple().exponent == -2
