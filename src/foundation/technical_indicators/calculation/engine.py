"""Execute declared calculations once per node and per current price batch."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ..errors import CalculationExecutionError, ResourceCleanupError
from ..sources.contracts import PriceBatch
from .calculation import BatchCalculationOutputs, CalculationOutput, CalculationSession, ControlReadStep
from .dependencies import CalculationPlan
from .sql_templates import load_sql_templates


class CalculationEngine:
    def __init__(self, executor, plan: CalculationPlan):
        self.executor = executor
        self.plan = plan
        self.sessions: dict[int, CalculationSession] = {}
        self._outputs: dict[int, CalculationOutput] = {}
        self._batch: PriceBatch | None = None
        self._prepared = False
        self._failed = False
        self._closed = False
        self._last_seq = 0
        self._template_texts: dict[tuple[str, str], str] = {}

    def _check_ready(self) -> None:
        self.executor.control.check_active()
        if not self._prepared or self._closed or self._failed:
            raise CalculationExecutionError("Calculation engine is not ready")

    def _session_for(self, node) -> CalculationSession:
        calculation_type = type(node.calculation)
        if getattr(calculation_type, "SQL_PACKAGE", None) != "src.foundation.technical_indicators.calculation":
            raise CalculationExecutionError("Calculation SQL must belong to the fixed calculation package")
        roles = getattr(calculation_type, "TABLE_ROLES", None)
        sql_files = getattr(calculation_type, "SQL_FILES", None)
        fixed = getattr(calculation_type, "FIXED_SQL_STEPS", None)
        if not isinstance(roles, Mapping) or not isinstance(sql_files, tuple) or not isinstance(fixed, Mapping):
            raise CalculationExecutionError("Calculation must declare its fixed tables and SQL steps")
        table_roles = {}
        for role, declaration in roles.items():
            if not isinstance(role, str) or not isinstance(declaration, tuple) or len(declaration) != 2:
                raise CalculationExecutionError("Calculation table roles have an invalid declaration")
            prefix, lifetime = declaration
            if lifetime not in {"state", "batch"}:
                raise CalculationExecutionError("Calculation table lifetime must be state or batch")
            name = f"{prefix}_{node.node_index}"
            self.executor._validate_name(name)
            table_roles[role] = (name, lifetime)
        names = tuple(name for name, _ in table_roles.values())
        if len(set(names)) != len(names):
            raise CalculationExecutionError("Calculation table roles cannot share an owned name")
        if not all(isinstance(name, str) and name.endswith(".sql") for name in sql_files):
            raise CalculationExecutionError("Calculation SQL file declarations require fixed file names")
        file_steps = tuple(name.removesuffix(".sql") for name in sql_files)
        step_names = (*file_steps, *fixed.keys())
        if len(set(step_names)) != len(step_names) or not all(isinstance(name, str) and name for name in step_names):
            raise CalculationExecutionError("Calculation SQL step names must be unique")
        control_reads = {}
        for name, value in fixed.items():
            if isinstance(value, ControlReadStep):
                if name not in {"read_smoothing_limits", "read_segment_bounds"}:
                    raise CalculationExecutionError("Unknown fixed calculation control SELECT")
                if any(role not in table_roles for role in value.input_roles):
                    raise CalculationExecutionError("Control SELECT references an undeclared owned table")
                control_reads[name] = value
            elif not isinstance(value, str):
                raise CalculationExecutionError("Calculation auxiliary SQL must be fixed text")
        return CalculationSession(
            self.executor, node.node_index, node.parameters, MappingProxyType({}), [], [],
            owned_table_names=frozenset(names), allowed_step_names=frozenset(step_names),
            table_roles=table_roles, control_read_steps=control_reads,
        )

    def prepare(self) -> None:
        self.executor.control.check_active()
        if self._prepared or self.sessions or self._closed or self._failed:
            raise CalculationExecutionError("Calculation engine can only be prepared once")
        try:
            known_names = set()
            for position, node in enumerate(self.plan.nodes):
                if node.node_index != position or any(index >= position or index < 0 for index in node.dependencies.values()):
                    raise CalculationExecutionError("Calculation plan must follow its declared dependency order")
                session = self._session_for(node)
                if known_names.intersection(session.owned_table_names):
                    raise CalculationExecutionError("Calculation nodes have conflicting owned table names")
                known_names.update(session.owned_table_names)
                # Save the session before preparing any of its resources.
                self.sessions[node.node_index] = session
                session.sql_templates = load_sql_templates(
                    type(node.calculation), request_texts=self._template_texts,
                    control=self.executor.control,
                )
                node.calculation.prepare(session)
            self._prepared = True
        except BaseException:
            self._failed = True
            raise

    def consume(self, batch: PriceBatch) -> None:
        self._check_ready()
        if self._batch is not None:
            raise CalculationExecutionError("Previous calculation batch has not been released")
        if (not isinstance(batch, PriceBatch) or type(batch.new_row_count) is not int
                or batch.new_row_count <= 0 or batch.new_first_seq != self._last_seq + 1
                or batch.new_last_seq - batch.new_first_seq + 1 != batch.new_row_count):
            raise CalculationExecutionError("Calculation price batch does not describe consecutive new positions")
        self._batch = batch
        self._outputs = {}
        try:
            for node in self.plan.nodes:
                self.executor.control.check_active()
                session = self.sessions[node.node_index]
                dependencies = {role: self._outputs[index] for role, index in node.dependencies.items()}
                for output in dependencies.values():
                    if (output.new_first_seq, output.new_last_seq) != (batch.new_first_seq, batch.new_last_seq):
                        raise CalculationExecutionError("Calculation dependency belongs to a different price batch")
                session.dependencies = MappingProxyType(dependencies)
                session.current_batch = batch
                session.readable_tables = frozenset({batch.table_name, *(output.table_name for output in dependencies.values())})
                output = node.calculation.consume(batch, session)
                if (not isinstance(output, CalculationOutput)
                        or (output.new_first_seq, output.new_last_seq) != (batch.new_first_seq, batch.new_last_seq)):
                    raise CalculationExecutionError("Calculation output belongs to a different price batch")
                readable = session.readable_tables | session.owned_table_names
                if output.table_name not in readable or output.sequence_field != "seq":
                    raise CalculationExecutionError("Calculation returned an undeclared result table")
                if output.fields != node.definition.output_fields:
                    raise CalculationExecutionError("Calculation output fields do not match its definition")
                self._outputs[node.node_index] = output
        except BaseException:
            self._failed = True
            raise

    def output_for(self, batch: PriceBatch) -> BatchCalculationOutputs:
        self._check_ready()
        if self._batch is not batch or len(self._outputs) != len(self.plan.nodes):
            raise CalculationExecutionError("No complete calculation output exists for this price batch")
        return BatchCalculationOutputs(batch, tuple((identity, self._outputs[index]) for identity, index in self.plan.instances))

    def release_batch_tables(self) -> None:
        self._check_ready()
        if self._batch is None:
            raise CalculationExecutionError("There is no current calculation batch to release")
        try:
            for node in reversed(self.plan.nodes):
                session = self.sessions[node.node_index]
                node.calculation.release_batch(session)
                if session.batch_tables:
                    raise CalculationExecutionError("Calculation did not release all of its batch tables")
                session.dependencies = MappingProxyType({})
                session.current_batch = None
                session.readable_tables = frozenset(session.state_tables)
            self._last_seq = self._batch.new_last_seq
            self._batch = None
            self._outputs.clear()
        except BaseException:
            self._failed = True
            raise

    def finish(self) -> None:
        self._check_ready()
        if self._batch is not None or self._outputs:
            raise CalculationExecutionError("Calculation engine has an unfinished price batch")

    def close(self) -> None:
        if self._closed:
            return
        errors = []
        try:
            for node in reversed(self.plan.nodes):
                session = self.sessions.get(node.node_index)
                if session is None:
                    continue
                session._cleanup_mode = True
                try:
                    node.calculation.release(session)
                    if session.batch_tables or session.state_tables:
                        raise ResourceCleanupError("Calculation left owned tables registered after release")
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    session._cleanup_mode = False
                    session.dependencies = MappingProxyType({})
                    session.current_batch = None
                    session.readable_tables = frozenset()
        finally:
            # SQL failures keep their ownership lists for diagnosis/cleanup;
            # package text has no reason to remain held by a stopped request.
            for session in self.sessions.values():
                session.sql_templates = MappingProxyType({})
            self._template_texts.clear()
            self._outputs.clear()
            self._batch = None
        if errors:
            error = ResourceCleanupError("Calculation engine resource cleanup failed")
            for item in errors:
                error.add_note(f"{type(item).__name__}: {item}")
            raise error from errors[0]
        self._closed = True
