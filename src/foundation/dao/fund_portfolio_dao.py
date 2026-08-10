from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, text, tuple_
from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.core_serving.fund_portfolio import FundPortfolio
from src.foundation.models.staging.fund_portfolio_stage import FundPortfolioStage


FUND_PORTFOLIO_IDENTITY_FIELDS = ("ts_code", "ann_date", "end_date", "symbol")
FUND_PORTFOLIO_SOURCE_FIELDS = (
    "ts_code",
    "ann_date",
    "end_date",
    "symbol",
    "mkv",
    "amount",
    "stk_mkv_ratio",
    "stk_float_ratio",
)


class FundPortfolioDAOError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class StagePageWriteResult:
    rows_staged: int
    rows_deduplicated: int


@dataclass(frozen=True, slots=True)
class StageFinalizeResult:
    rows_source_unique: int
    rows_inserted: int
    rows_matched: int
    final_scope_count: int


class FundPortfolioDAO(BaseDAO[FundPortfolioStage]):
    """Set-based staged publisher for one immutable fund-portfolio scope."""

    final_model = FundPortfolio
    identity_fields = FUND_PORTFOLIO_IDENTITY_FIELDS
    source_fields = FUND_PORTFOLIO_SOURCE_FIELDS

    def __init__(self, session: Session) -> None:
        super().__init__(session, FundPortfolioStage)

    @staticmethod
    def advisory_lock_key(dataset_key: str) -> int:
        material = f"serving_staged_immutable_scope_publish\x1f{dataset_key}"
        unsigned = int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")
        return unsigned if unsigned < 2**63 else unsigned - 2**64

    def acquire_execution_lock(self, *, dataset_key: str) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        acquired = self.session.scalar(select(func.pg_try_advisory_lock(self.advisory_lock_key(dataset_key))))
        if not acquired:
            raise FundPortfolioDAOError("staged_scope_busy", "基金持仓 staged publisher 已有执行占用")

    def release_execution_lock(self, *, dataset_key: str) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        self.session.scalar(select(func.pg_advisory_unlock(self.advisory_lock_key(dataset_key))))

    def clear_stage(self) -> int:
        result = self.session.execute(delete(FundPortfolioStage))
        return max(int(result.rowcount or 0), 0)

    def cleanup_stage_run(self, *, stage_run_id: UUID) -> int:
        result = self.session.execute(delete(FundPortfolioStage).where(FundPortfolioStage.stage_run_id == stage_run_id))
        return max(int(result.rowcount or 0), 0)

    def stage_page(
        self,
        *,
        stage_run_id: UUID,
        period: date,
        repair_ts_code: str | None,
        rows: list[dict[str, Any]],
    ) -> StagePageWriteResult:
        # Delayed import avoids DAOFactory -> ingestion package -> resolver ->
        # DAOFactory initialization cycles. The same shared deterministic hash
        # contract is still used at execution time.
        from src.foundation.ingestion.observed_snapshot import compute_source_content_hash

        prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
        duplicates = 0
        for row in rows:
            if row.get("end_date") != period:
                raise FundPortfolioDAOError(
                    "stage_scope_mismatch",
                    "源端基金持仓报告期与请求 period 不一致",
                    details={"expected_period": period.isoformat(), "actual_period": str(row.get("end_date"))},
                )
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if repair_ts_code is not None and ts_code != repair_ts_code:
                raise FundPortfolioDAOError(
                    "stage_scope_mismatch",
                    "源端基金代码与定向补录代码不一致",
                    details={"expected_ts_code": repair_ts_code, "actual_ts_code": ts_code},
                )
            content_hash = compute_source_content_hash(row=row, source_fields=self.source_fields)
            identity = tuple(row[field] for field in self.identity_fields)
            existing = prepared.get(identity)
            if existing is not None:
                if existing["source_content_hash"] != content_hash:
                    raise FundPortfolioDAOError(
                        "stage_identity_content_conflict",
                        "同一基金持仓身份在同页出现不同内容",
                        details={"identity": [str(value) for value in identity]},
                    )
                duplicates += 1
                continue
            prepared[identity] = {
                **{field: row.get(field) for field in self.source_fields},
                "stage_run_id": stage_run_id,
                "source_content_hash": content_hash,
            }

        identities = list(prepared)
        existing_stage: dict[tuple[Any, ...], str] = {}
        if identities:
            identity_columns = tuple(getattr(FundPortfolioStage, field) for field in self.identity_fields)
            statement = select(*identity_columns, FundPortfolioStage.source_content_hash).where(
                FundPortfolioStage.stage_run_id == stage_run_id,
                tuple_(*identity_columns).in_(identities),
            )
            for result_row in self.session.execute(statement):
                existing_stage[tuple(result_row[:-1])] = str(result_row[-1])

        new_rows: list[dict[str, Any]] = []
        for identity, row in prepared.items():
            previous_hash = existing_stage.get(identity)
            if previous_hash is None:
                new_rows.append(row)
                continue
            if previous_hash != row["source_content_hash"]:
                raise FundPortfolioDAOError(
                    "stage_identity_content_conflict",
                    "同一基金持仓身份跨页出现不同内容",
                    details={"identity": [str(value) for value in identity]},
                )
            duplicates += 1
        if new_rows:
            self.session.execute(FundPortfolioStage.__table__.insert(), new_rows)
        return StagePageWriteResult(rows_staged=len(new_rows), rows_deduplicated=duplicates)

    def finalize_scope(
        self,
        *,
        stage_run_id: UUID,
        period: date,
        repair_ts_code: str | None,
    ) -> StageFinalizeResult:
        stage_run_param: UUID | str = stage_run_id
        if self.session.get_bind().dialect.name != "postgresql":
            stage_run_param = stage_run_id.hex
        params: dict[str, Any] = {"stage_run_id": stage_run_param, "period": period}
        repair_stage = ""
        repair_final = ""
        if repair_ts_code is not None:
            params["repair_ts_code"] = repair_ts_code
            repair_stage = " AND s.ts_code = :repair_ts_code"
            repair_final = " AND f.ts_code = :repair_ts_code"

        stage_count = int(
            self.session.scalar(
                text(
                    "SELECT count(*) FROM foundation.fund_portfolio_stage s "
                    "WHERE s.stage_run_id = :stage_run_id AND s.end_date = :period" + repair_stage
                ),
                params,
            )
            or 0
        )
        if stage_count <= 0:
            raise FundPortfolioDAOError("staged_scope_empty", "基金持仓 staged scope 为空")

        join_identity = (
            "f.end_date = s.end_date AND f.ts_code = s.ts_code "
            "AND f.ann_date = s.ann_date AND f.symbol = s.symbol"
        )
        existing_count = int(
            self.session.scalar(
                text("SELECT count(*) FROM core_serving.fund_portfolio f WHERE f.end_date = :period" + repair_final),
                params,
            )
            or 0
        )
        regression_count = int(
            self.session.scalar(
                text(
                    "SELECT count(*) FROM core_serving.fund_portfolio f "
                    "WHERE f.end_date = :period" + repair_final +
                    " AND NOT EXISTS (SELECT 1 FROM foundation.fund_portfolio_stage s "
                    "WHERE s.stage_run_id = :stage_run_id AND " + join_identity + ")"
                ),
                params,
            )
            or 0
        )
        if regression_count:
            raise FundPortfolioDAOError(
                "immutable_scope_regression",
                "源端基金持仓 scope 少于已发布不可变事实",
                details={"missing_existing_rows": regression_count},
            )
        conflict_count = int(
            self.session.scalar(
                text(
                    "SELECT count(*) FROM foundation.fund_portfolio_stage s "
                    "JOIN core_serving.fund_portfolio f ON " + join_identity +
                    " WHERE s.stage_run_id = :stage_run_id AND s.end_date = :period" + repair_stage +
                    " AND f.source_content_hash <> s.source_content_hash"
                ),
                params,
            )
            or 0
        )
        if conflict_count:
            raise FundPortfolioDAOError(
                "immutable_content_conflict",
                "已发布基金持仓身份对应的源内容发生变化",
                details={"conflicting_rows": conflict_count},
            )

        columns = ", ".join((*self.source_fields, "source_content_hash"))
        selected = ", ".join(f"s.{column}" for column in (*self.source_fields, "source_content_hash"))
        self.session.execute(
            text(
                f"INSERT INTO core_serving.fund_portfolio ({columns}) "
                f"SELECT {selected} FROM foundation.fund_portfolio_stage s "
                "WHERE s.stage_run_id = :stage_run_id AND s.end_date = :period" + repair_stage +
                " AND NOT EXISTS (SELECT 1 FROM core_serving.fund_portfolio f WHERE " + join_identity + ")"
            ),
            params,
        )
        rows_inserted = stage_count - existing_count
        final_count = int(
            self.session.scalar(
                text("SELECT count(*) FROM core_serving.fund_portfolio f WHERE f.end_date = :period" + repair_final),
                params,
            )
            or 0
        )
        if final_count != stage_count or rows_inserted + existing_count != stage_count:
            raise FundPortfolioDAOError(
                "staged_scope_reconciliation_failed",
                "基金持仓最终 scope 与 staged scope 行数不一致",
                details={
                    "stage_count": stage_count,
                    "existing_count": existing_count,
                    "rows_inserted": rows_inserted,
                    "final_count": final_count,
                },
            )
        return StageFinalizeResult(
            rows_source_unique=stage_count,
            rows_inserted=rows_inserted,
            rows_matched=existing_count,
            final_scope_count=final_count,
        )
