"""Read the published DG ETF daily files and their ETF Basic reference."""

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
import re
from stat import S_ISREG
from threading import Timer
from time import monotonic

import duckdb
import httpx

from src.foundation.clients.local_lake.reference_data_reader import LakeTradeCalendarReader

_DUCKDB_CONFIG = {"threads": "1", "max_temp_directory_size": "0B"}
_DAILY_DIRECTORY = "silver/quote/etf_daily"
_BASIC_DIRECTORY = "silver/basic/etf_basic"
_PART_FILE = "part-000.parquet"
_DG_GRAPHQL_URL = "http://127.0.0.1:3000/graphql"
_MATERIALIZATION = """
query EtfActivityBasic($day: String!) {
  assetNodeOrError(assetKey: {path: ["silver_etf_daily"]}) {
    __typename
    ... on AssetNode {
      assetMaterializations(partitions: [$day], limit: 1) {
        partition
        metadataEntries {
          label
          ... on TextMetadataEntry { text }
          ... on PathMetadataEntry { path }
        }
      }
    }
  }
}
"""


class EtfDailyReadError(RuntimeError):
    """A required DG file or materialization reference could not be used."""


def remaining_etf_read_seconds(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("本地 ETF 日线读取超时")
    return remaining


class EtfDailyLakeReader:
    def __init__(self, root: Path | None) -> None:
        self.root = root
        self.calendar = LakeTradeCalendarReader(root, connection_config=_DUCKDB_CONFIG)

    def daily_files(self, *, through: date, deadline: float) -> dict[date, Path]:
        root = self.root
        if root is None:
            raise EtfDailyReadError("ETF 动态未配置正式 DG 根目录")
        directory = root / _DAILY_DIRECTORY
        try:
            if not directory.resolve().is_relative_to(root):
                raise EtfDailyReadError("ETF 日线目录不在正式 DG 根目录")
            try:
                partitions = list(directory.iterdir())
            except FileNotFoundError:
                # The calendar read still distinguishes an empty lake from an unavailable mount.
                return {}
            files = {}
            for partition in partitions:
                remaining_etf_read_seconds(deadline)
                if not partition.name.startswith("trade_date="):
                    continue
                try:
                    day = date.fromisoformat(partition.name.removeprefix("trade_date="))
                except ValueError:
                    continue
                if day > through or partition.name != f"trade_date={day.isoformat()}":
                    continue
                path = partition / _PART_FILE
                try:
                    if S_ISREG(path.stat().st_mode):
                        files[day] = path
                except FileNotFoundError:
                    continue
            return files
        except OSError as exc:
            raise EtfDailyReadError("无法枚举本地 DG ETF 日线分区") from exc

    def basic_file(self, *, day: date, daily_file: Path, deadline: float) -> Path:
        # `daily_file` was located under root by daily_files for this same request.
        assert self.root is not None
        try:
            with httpx.Client(trust_env=False) as client:
                response = client.post(
                    _DG_GRAPHQL_URL,
                    json={"query": _MATERIALIZATION, "variables": {"day": day.isoformat()}},
                    timeout=remaining_etf_read_seconds(deadline),
                )
                response.raise_for_status()
                payload = response.json()
            remaining_etf_read_seconds(deadline)
            if not isinstance(payload, dict) or payload.get("errors"):
                raise ValueError("DG GraphQL 查询失败")
            asset = payload["data"]["assetNodeOrError"]
            if asset["__typename"] != "AssetNode":
                raise ValueError("DG ETF 日线资产不可用")
            events = asset["assetMaterializations"]
            if len(events) != 1 or events[0]["partition"] != day.isoformat():
                raise ValueError("缺少同日的 DG ETF 日线物化记录")
            metadata = {
                entry["label"]: entry.get("text", entry.get("path"))
                for entry in events[0]["metadataEntries"]
            }
            if metadata["dagster/uri"] != str(daily_file):
                raise ValueError("DG 日线物化路径与当前文件不一致")
            snapshot_id = metadata["goldenshare/basic_raw_snapshot_hash"]
            if not re.fullmatch(r"[a-f0-9]{64}", snapshot_id):
                raise ValueError("DG ETF 基础信息快照标识无效")
            path = self.root / _BASIC_DIRECTORY / f"snapshot_id={snapshot_id}" / _PART_FILE
            if (
                metadata["goldenshare/basic_silver_uri"] != str(path)
                or not path.resolve().is_relative_to(self.root)
            ):
                raise ValueError("DG ETF 基础信息快照路径无效")
            return path
        except (httpx.HTTPError, KeyError, TypeError, ValueError, OSError) as exc:
            raise EtfDailyReadError("无法取得同日 DG ETF 基础信息快照引用") from exc

    def query_parquet(
        self,
        sql: str,
        parameters: list,
        *,
        columns_by_file: Mapping[Path, Mapping[str, str]],
        deadline: float,
    ) -> Sequence[tuple]:
        paths = list(columns_by_file)
        assert self.root is not None
        try:
            if any(not path.resolve().is_relative_to(self.root) for path in paths):
                raise EtfDailyReadError("ETF 数据文件不在正式 DG 根目录")
            remaining_etf_read_seconds(deadline)
            with duckdb.connect(":memory:", config=_DUCKDB_CONFIG) as connection:
                timer = Timer(remaining_etf_read_seconds(deadline), connection.interrupt)
                timer.daemon = True
                timer.start()
                try:
                    expected = {
                        (str(path), column): datatype
                        for path, columns in columns_by_file.items()
                        for column, datatype in columns.items()
                    }
                    columns = sorted({column for _, column in expected})
                    schema_rows = connection.execute(
                        """SELECT file_name, name, duckdb_type FROM parquet_schema(?)
                           WHERE name IN (SELECT unnest(?::VARCHAR[]))""",
                        [[str(path) for path in paths], columns],
                    ).fetchall()
                    actual = {(path, column): datatype for path, column, datatype in schema_rows}
                    if any(actual.get(key) != datatype for key, datatype in expected.items()):
                        raise EtfDailyReadError("DG ETF Parquet 投影字段与类型不符合合同")
                    remaining_etf_read_seconds(deadline)
                    rows = connection.execute(sql, parameters).fetchall()
                    remaining_etf_read_seconds(deadline)
                    return rows
                finally:
                    timer.cancel()
                    timer.join()
        except duckdb.InterruptException as exc:
            raise TimeoutError("本地 ETF 日线读取超时") from exc
        except (duckdb.Error, OSError) as exc:
            raise EtfDailyReadError("DG ETF Parquet 读取或计算失败") from exc
