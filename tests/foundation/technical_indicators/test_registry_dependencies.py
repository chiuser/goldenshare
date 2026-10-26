"""LLD §04/§07/§19.2: structural contracts, without data or numerical SQL.

The test-only calculation borrows the described price table as its output. It
implements all six Calculation methods, but is never a production algorithm.
Expected graph indices and parameter values below are independent literal
examples of the declared dependency rules.
"""

from dataclasses import FrozenInstanceError, dataclass, replace

import pytest

from src.foundation.technical_indicators.calculation.calculation import (
    CalculationDefinition,
    CalculationOutput,
    CalculationSession,
    Dependency,
    OutputField,
    ParameterSpec,
)
from src.foundation.technical_indicators.calculation.history import (
    HistoryRequirement,
    combine_history_and_fields,
)
from src.foundation.technical_indicators.calculation.registry import CalculationRegistry
from src.foundation.technical_indicators.contracts import CalculationInstance, CalculationRequest, Parameters
from src.foundation.technical_indicators.discovery import (
    SourceCapability,
    describe_calculation,
    list_calculations,
)
from src.foundation.technical_indicators.errors import CalculationUnsupportedError, RequestInvalidError
from src.foundation.technical_indicators.sources.contracts import PriceBatch


FIELD = OutputField("value", "close", "DOUBLE", False, "Every current bar")


@dataclass(frozen=True, slots=True)
class BorrowedPriceCalculation:
    parameters: Parameters
    declared_dependencies: tuple[Dependency, ...] = ()

    def input_requirement(self, session, max_input_rows):
        return HistoryRequirement(frozenset({"close"}), 0, 0, False, (), "Every current bar")

    def dependencies(self):
        return self.declared_dependencies

    def prepare(self, session):
        session.initialized = True

    def consume(self, batch, session):
        assert session.initialized
        return CalculationOutput(batch.table_name, (FIELD,), batch.new_first_seq, batch.new_last_seq)

    def release_batch(self, session):
        # The borrowed source table is never this object's owned resource.
        assert not session.batch_tables

    def release(self, session):
        assert not session.state_tables and not session.batch_tables
        session.initialized = False


def definition(calculation_id="custom", *, public=True, version="1.0.0", periods=("day", "week")):
    return CalculationDefinition(
        calculation_id=calculation_id,
        algorithm_version=version,
        description="Test table borrowing contract",
        parameter_specs=(ParameterSpec("period", "positive_integer", 20),),
        input_fields=frozenset({"close"}),
        output_fields=(FIELD,),
        initialization="Every current bar",
        history_rule="No preceding bars",
        units=(("value", "source_price_unit"),),
        supported_periods=periods,
        public=public,
    )


def request(*instances, period="day"):
    return CalculationRequest("stock", "000001.SZ", period, instances)


def instance(identity="one", calculation_id="custom", **parameters):
    return CalculationInstance(identity, calculation_id, parameters)


def frozen_registry(*registrations):
    registry = CalculationRegistry()
    for item, factory in registrations:
        registry.register(item, factory)
    registry.freeze()
    return registry


def test_registry_requires_actual_factory_and_rejects_duplicate_ids_or_versions():
    registry = CalculationRegistry()
    registered = definition()
    with pytest.raises(RequestInvalidError, match="callable"):
        registry.register(registered, None)
    registry.register(registered, BorrowedPriceCalculation)
    for conflicting in (registered, replace(registered, algorithm_version="2.0.0")):
        with pytest.raises(RequestInvalidError, match="one registered"):
            registry.register(conflicting, BorrowedPriceCalculation)
    assert registry.resolve("custom") is registered


def test_freeze_is_idempotent_and_runtime_cannot_extend_registry():
    registry = frozen_registry((definition(), BorrowedPriceCalculation))
    registry.freeze()
    with pytest.raises(RequestInvalidError, match="frozen"):
        registry.register(definition("second"), BorrowedPriceCalculation)
    assert tuple(item.calculation_id for item in registry.public_definitions()) == ("custom",)


def test_planning_rejects_unfrozen_registry():
    registry = CalculationRegistry()
    registry.register(definition(), BorrowedPriceCalculation)
    with pytest.raises(RequestInvalidError, match="Freeze"):
        registry.expand_dependencies(request(instance()))


def test_public_and_internal_resolution_enforce_visibility_and_exact_version():
    internal = definition("window_mean", public=False)
    registry = frozen_registry((internal, BorrowedPriceCalculation))
    assert registry.resolve_dependency("window_mean", "1.0.0") is internal
    for operation in (
        lambda: registry.resolve("window_mean"),
        lambda: registry.resolve("missing"),
        lambda: registry.resolve_dependency("window_mean", "2.0.0"),
        lambda: registry.resolve_dependency("missing", "1.0.0"),
    ):
        with pytest.raises(CalculationUnsupportedError):
            operation()


@pytest.mark.parametrize("bad_instance", [
    instance("bad", period=0),
    instance("bad", period=True),
    instance("bad", unknown=12),
    instance("bad", calculation_id="missing"),
])
def test_all_public_requests_are_validated_before_any_factory(bad_instance):
    created = []

    def factory(parameters):
        created.append(parameters)
        return BorrowedPriceCalculation(parameters)

    registry = frozen_registry((definition(), factory))
    with pytest.raises((RequestInvalidError, CalculationUnsupportedError)):
        registry.expand_dependencies(request(instance("good"), bad_instance))
    assert created == []


def test_unsupported_period_is_rejected_before_factory_but_declared_period_is_accepted():
    created = []

    def factory(parameters):
        created.append(parameters)
        return BorrowedPriceCalculation(parameters)

    registry = frozen_registry((definition(periods=("week",)), factory))
    with pytest.raises(CalculationUnsupportedError, match="period"):
        registry.expand_dependencies(request(instance()))
    assert created == []
    plan = registry.expand_dependencies(request(instance(), period="week"))
    assert plan.nodes[0].parameters == (("period", 20),)


def test_factory_precedes_dependency_declaration_and_parameters_are_normalized():
    events = []

    @dataclass(frozen=True, slots=True)
    class RecordedCalculation(BorrowedPriceCalculation):
        def dependencies(self):
            events.append(("dependencies", self.parameters))
            return ()

    def factory(parameters):
        events.append(("factory", parameters))
        return RecordedCalculation(parameters)

    custom = replace(definition(), parameter_specs=(
        ParameterSpec("first", "positive_integer", 1),
        ParameterSpec("second", "positive_integer", 2),
    ))
    registry = frozen_registry((custom, factory))
    plan = registry.expand_dependencies(request(instance(second=7)))
    expected = (("first", 1), ("second", 7))
    assert events == [("factory", expected), ("dependencies", expected)]
    assert plan.nodes[0].parameters == expected


def test_request_local_sharing_retains_instance_identity_and_stable_dependency_order():
    calls = []

    def factory_for(identity, dependencies=()):
        def factory(parameters):
            calls.append((identity, parameters))
            declared = tuple(Dependency(role, target, "1.0.0", parameters) for role, target in dependencies)
            return BorrowedPriceCalculation(parameters, declared)
        return factory

    registry = frozen_registry(
        (definition("ma"), factory_for("ma", (("mean", "window_mean"),))),
        (definition("boll"), factory_for("boll", (("mean", "window_mean"),))),
        (definition("window_mean", public=False), factory_for("window_mean")),
    )
    plan = registry.expand_dependencies(request(
        instance("ma20", "ma"), instance("boll20", "boll", period=20),
        instance("ma20_again", "ma", period=20), instance("ma21", "ma", period=21),
    ))
    assert [node.definition.calculation_id for node in plan.nodes] == [
        "window_mean", "ma", "boll", "window_mean", "ma",
    ]
    assert [node.node_index for node in plan.nodes] == [0, 1, 2, 3, 4]
    assert plan.instances == (("ma20", 1), ("boll20", 2), ("ma20_again", 1), ("ma21", 4))
    assert dict(plan.nodes[1].dependencies) == {"mean": 0}
    assert dict(plan.nodes[2].dependencies) == {"mean": 0}
    assert dict(plan.nodes[4].dependencies) == {"mean": 3}
    assert calls == [
        ("ma", (("period", 20),)), ("window_mean", (("period", 20),)),
        ("boll", (("period", 20),)), ("ma", (("period", 21),)),
        ("window_mean", (("period", 21),)),
    ]
    assert combine_history_and_fields(node.calculation.input_requirement(None, 1500000) for node in plan.nodes).fields == frozenset({"close"})


def test_multiple_roles_keep_declared_order_and_share_completed_upstream():
    dependencies = (
        Dependency("second", "second", "1.0.0", ()),
        Dependency("first", "first", "1.0.0", ()),
        Dependency("same_second", "second", "1.0.0", (("period", 20),)),
    )
    registry = frozen_registry(
        (definition(), lambda parameters: BorrowedPriceCalculation(parameters, dependencies)),
        (definition("first", public=False), BorrowedPriceCalculation),
        (definition("second", public=False), BorrowedPriceCalculation),
    )
    plan = registry.expand_dependencies(request(instance()))
    assert [node.definition.calculation_id for node in plan.nodes] == ["second", "first", "custom"]
    assert tuple(plan.nodes[2].dependencies.items()) == (("second", 0), ("first", 1), ("same_second", 0))


@pytest.mark.parametrize("upstream,version", [("custom", "1.0.0"), ("missing", "1.0.0"), ("known", "2.0.0")])
def test_cycles_unknown_dependencies_and_unregistered_versions_are_rejected(upstream, version):
    dependency = Dependency("input", upstream, version, ())
    registry = frozen_registry(
        (definition(), lambda parameters: BorrowedPriceCalculation(parameters, (dependency,))),
        (definition("known", public=False), BorrowedPriceCalculation),
    )
    with pytest.raises((RequestInvalidError, CalculationUnsupportedError)):
        registry.expand_dependencies(request(instance()))


def test_indirect_dependency_cycle_is_rejected():
    registry = frozen_registry(
        (definition(), lambda p: BorrowedPriceCalculation(p, (Dependency("input", "hidden", "1.0.0", p),))),
        (definition("hidden", public=False), lambda p: BorrowedPriceCalculation(p, (Dependency("input", "custom", "1.0.0", p),))),
    )
    with pytest.raises(RequestInvalidError, match="cycle"):
        registry.expand_dependencies(request(instance()))


@pytest.mark.parametrize("dependencies", [
    (Dependency("", "hidden", "1.0.0", ()),),
    (Dependency("same", "hidden", "1.0.0", ()), Dependency("same", "hidden", "1.0.0", ())),
    (Dependency("one", "hidden", "1.0.0", (("period", 1), ("period", 2))),),
    (Dependency("one", "hidden", "1.0.0", (("unknown", 1),)),),
    (Dependency("one", "hidden", "1.0.0", (("period", 0),)),),
])
def test_invalid_dependency_declarations_fail_before_execution(dependencies):
    registry = frozen_registry(
        (definition(), lambda p: BorrowedPriceCalculation(p, dependencies)),
        (definition("hidden", public=False), BorrowedPriceCalculation),
    )
    with pytest.raises((RequestInvalidError, CalculationUnsupportedError)):
        registry.expand_dependencies(request(instance()))


def test_dependency_period_must_also_be_supported():
    dependency = Dependency("input", "weekly", "1.0.0", ())
    registry = frozen_registry(
        (definition(), lambda p: BorrowedPriceCalculation(p, (dependency,))),
        (definition("weekly", public=False, periods=("week",)), BorrowedPriceCalculation),
    )
    with pytest.raises(CalculationUnsupportedError, match="period"):
        registry.expand_dependencies(request(instance()))


def test_incomplete_factory_output_is_rejected():
    registry = frozen_registry((definition(), lambda p: object()))
    with pytest.raises(RequestInvalidError, match="complete Calculation"):
        registry.expand_dependencies(request(instance()))


def test_plans_and_dependency_maps_are_immutable_and_nodes_are_not_shared_across_requests():
    registry = frozen_registry((definition(), BorrowedPriceCalculation))
    first = registry.expand_dependencies(request(instance()))
    second = registry.expand_dependencies(request(instance()))
    assert first.nodes is not second.nodes
    assert first.nodes[0] is not second.nodes[0]
    assert first.nodes[0].calculation is not second.nodes[0].calculation
    assert first.nodes[0].definition is second.nodes[0].definition
    with pytest.raises(FrozenInstanceError):
        first.nodes = ()
    with pytest.raises(FrozenInstanceError):
        first.nodes[0].parameters = ()
    with pytest.raises(TypeError):
        first.nodes[0].dependencies["input"] = 0


def test_test_calculation_has_a_complete_borrowed_table_contract_without_numerical_execution():
    calculation = BorrowedPriceCalculation(())
    session = CalculationSession(object(), 0, (), {}, [], [])
    price_batch = PriceBatch("prepared_prices", 10, 12, 3, 0, ("trade_date",), ("close",), "qfq")
    calculation.prepare(session)
    result = calculation.consume(price_batch, session)
    assert result == CalculationOutput("prepared_prices", (FIELD,), 10, 12)
    calculation.release_batch(session)
    calculation.release(session)
    calculation.release(session)
    assert session.initialized is False


def test_discovery_uses_registry_definition_objects_hides_internal_steps_and_does_not_invoke_factory():
    created = []

    def factory(parameters):
        created.append(parameters)
        return BorrowedPriceCalculation(parameters)

    custom = definition()
    registry = frozen_registry((custom, factory), (definition("hidden", public=False), factory))
    catalog = list_calculations(registry)
    assert len(catalog) == 1
    assert catalog[0].definition is custom
    assert catalog[0].source_capabilities == ()
    assert catalog[0].source_supported is False
    assert describe_calculation(registry, "custom") == catalog[0]
    assert created == []
    for calculation_id in ("hidden", "missing"):
        with pytest.raises(CalculationUnsupportedError):
            describe_calculation(registry, calculation_id)


def test_discovery_reports_only_explicit_matching_source_declarations():
    registry = frozen_registry((definition(periods=("week",)), BorrowedPriceCalculation))
    daily = SourceCapability("stock", "day", "qfq", "gold_stock_day")
    weekly = SourceCapability("stock", "week", "qfq", "configured_week_source")
    declaration = [daily, weekly]
    description = describe_calculation(registry, "custom", source_capabilities=declaration)
    declaration.clear()
    assert description.source_capabilities == (weekly,)
    assert description.source_supported is True
    assert describe_calculation(registry, "custom", source_capabilities=(daily,)).source_supported is False
    with pytest.raises(FrozenInstanceError):
        weekly.period = "day"
    with pytest.raises(FrozenInstanceError):
        description.source_supported = False
