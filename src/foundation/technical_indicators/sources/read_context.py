"""Request-local resource accounting; no data quality or completeness audit."""

from pathlib import Path

from ..configuration.settings import KernelConfig
from ..errors import ResourceLimitError


class SourceReadContext:
    SQL_PACKAGE = "src.foundation.technical_indicators.sources"
    SQL_FILES = ("stage_input.sql", "adjust_price.sql", "retain_history.sql")

    def __init__(self, config: KernelConfig):
        self.config = config
        self._files: dict[Path, int] = {}
        self._source_rows = 0
        self._locator_rows = 0
        self._source_file_bytes = 0
        self._sql_texts: dict[tuple[str, str], str] = {}
        self._basis_row = None

    def sql_template(self, name: str, *, control) -> str:
        from ..calculation.sql_templates import load_sql_templates

        return load_sql_templates(type(self), request_texts=self._sql_texts,
                                  control=control, requested_files=(name,))[name]

    def remember_basis(self, description, request, path: Path) -> None:
        self._basis_row = (description.source_id, request.ts_code, Path(path),
                           description.basis_date, description.basis_value)

    def reusable_basis(self, description, request, selected_dates, selected_paths):
        row = self._basis_row
        if (row is not None and row[0] == description.source_id and row[1] == request.ts_code
                and row[2] in selected_paths and row[3] in selected_dates
                and row[3] == description.basis_date and row[4] == description.basis_value):
            return row[2:]
        return None

    def clear_request_metadata(self) -> None:
        self._sql_texts.clear()
        self._basis_row = None

    def record_file(self, path: Path, size_bytes: int) -> None:
        path = Path(path)
        if path not in self._files:
            if len(self._files) >= self.config.max_source_files:
                raise ResourceLimitError("Source files exceed max_source_files")
            self._files[path] = size_bytes
            self._source_file_bytes += size_bytes

    def record_price_rows(self, rows: int) -> None:
        """Charge a first physical read once, before copying or delivery.

        Delivering a buffered remainder does not charge it again. A rejected
        over-limit read is not admitted to this counter; diagnostics separately
        record actual reader rows, including that rejected read.
        """
        if self._source_rows + rows > self.config.max_input_rows:
            raise ResourceLimitError("Source price rows exceed max_input_rows")
        self._source_rows += rows

    @property
    def locator_rows(self) -> int:
        return self._locator_rows

    def record_locator_rows(self, rows: int) -> None:
        if type(rows) is not int or rows < 0:
            raise ValueError("Locator rows require a nonnegative integer")
        self._locator_rows += rows

    @property
    def source_files(self) -> int:
        return len(self._files)

    @property
    def source_file_bytes(self) -> int:
        return self._source_file_bytes

    @property
    def source_rows(self) -> int:
        return self._source_rows
