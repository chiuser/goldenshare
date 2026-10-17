"""Only the fourteen fixed update sensors; never registration or cursor changes."""

import json
import time
from datetime import datetime

from dagster._core.storage.runs.schema import RunsTable
from sqlalchemy import select

from orchestrator.defs.bootstrap.moneyflow_history_supplement_control import (
    CONTRACTS,
    require,
)
from orchestrator.moneyflow_continuation.contract import ACTIVE, REPOSITORY

START = "mutation($selector:SensorSelector!){startSensor(sensorSelector:$selector){__typename ... on Sensor{name sensorState{id status}} ... on PythonError{message}}}"
STOP = "mutation($id:String!){stopSensor(id:$id){__typename ... on StopSensorMutationResult{instigationState{id status}} ... on PythonError{message}}}"
FIELDS = "__typename ... on Sensor{name defaultStatus minIntervalSeconds targets{pipelineName} sensorState{id status typeSpecificData{__typename ... on SensorData{lastCursor}}}}"
NAMES = tuple(
    job + "_sensor" for c in CONTRACTS.values() for job in (c.raw_job, c.silver_job)
)


def same_sensor_cursor(actual, expected):
    """Never reset progress; only the producer's observation time may differ."""
    if actual == expected:
        return True
    fields = {
        "schema_version",
        "evaluated_at",
        "decision",
        "target_date",
        "selected_count",
        "blocked_count",
        "sample_keys",
        "details",
    }
    try:
        values = [json.loads(value) for value in (actual, expected)]
        for value in values:
            if (
                not isinstance(value, dict)
                or set(value) != fields
                or type(value["schema_version"]) is not int
                or value["schema_version"] != 1
                or not isinstance(value["evaluated_at"], str)
                or datetime.fromisoformat(value["evaluated_at"]).utcoffset() is None
            ):
                return False
            del value["evaluated_at"]
        return values[0] == values[1]
    except (TypeError, ValueError):
        return False


def same_sensor_state(actual, expected):
    return (
        isinstance(actual, dict)
        and isinstance(expected, dict)
        and set(actual) == set(expected) == {"id", "status", "cursor"}
        and actual["id"] == expected["id"]
        and actual["status"] == expected["status"]
        and same_sensor_cursor(actual["cursor"], expected["cursor"])
    )


def same_sensor_snapshot(actual, expected):
    return set(actual) == set(expected) == set(NAMES) and all(
        same_sensor_state(actual[n], expected[n]) for n in NAMES
    )


def snapshot_body():
    declarations = ",".join(f"$s{i}:SensorSelector!" for i in range(len(NAMES)))
    selections = " ".join(
        f"a{i}:sensorOrError(sensorSelector:$s{i}){{{FIELDS}}}"
        for i in range(len(NAMES))
    )
    return {
        "query": f"query({declarations}){{{selections}}}",
        "variables": {
            f"s{i}": {**REPOSITORY, "sensorName": name} for i, name in enumerate(NAMES)
        },
    }


class Updates:
    def __init__(self, backend):
        self.backend = backend

    def snapshot(self):
        data = self.backend.http(snapshot_body())["data"]
        result = {}
        for i, name in enumerate(NAMES):
            value = data[f"a{i}"]
            require(
                value.get("__typename") == "Sensor"
                and value["name"] == name
                and value["defaultStatus"] == "STOPPED"
                and value["minIntervalSeconds"] == 600
                and [t["pipelineName"] for t in value["targets"]]
                == [name.removesuffix("_sensor")],
                "sensor_contract",
            )
            state = value["sensorState"]
            require(state["status"] in {"RUNNING", "STOPPED"}, "sensor_status")
            result[name] = {
                "id": state["id"],
                "status": state["status"],
                "cursor": (state.get("typeSpecificData") or {}).get("lastCursor"),
            }
        return result

    def set_status(self, name, identity, status):
        require(name in NAMES and status in {"RUNNING", "STOPPED"}, "sensor_action")
        body = (
            {
                "query": START,
                "variables": {"selector": {**REPOSITORY, "sensorName": name}},
            }
            if status == "RUNNING"
            else {"query": STOP, "variables": {"id": identity}}
        )
        self.backend.http(body, mutation=True)


def transition(updates, control, *, restore=False):
    original = control.plan["sensors"]
    current = control.read(updates.snapshot)
    if not restore and not control.state["sensors"]:
        require(same_sensor_snapshot(current, original), "sensor_baseline_changed")
    for name in NAMES:
        saved = original[name]
        require(
            current[name]["id"] == saved["id"]
            and same_sensor_cursor(current[name]["cursor"], saved["cursor"]),
            "sensor_identity_changed",
        )
        desired = saved["status"] if restore else "STOPPED"
        key = ("restore:" if restore else "pause:") + name
        if current[name]["status"] != desired:
            require(saved["status"] == "RUNNING", "original_stopped_changed")
            require(
                control.state["sensors"].get(key) != "intent", "sensor_result_uncertain"
            )
            if restore:
                if control.state["sensors"].get("pause:" + name) == "intent":
                    # The preceding bounded native read proves the lost pause response.
                    control.state["sensors"]["pause:" + name] = "complete"
                    control.save()
                require(
                    control.state["sensors"].get("pause:" + name) == "complete",
                    "sensor_not_paused_by_operation",
                )
            control.check()
            control.state["sensors"][key] = "intent"
            control.save()
            updates.set_status(name, saved["id"], desired)
            current = control.read(updates.snapshot)
            require(
                same_sensor_state(current[name], {**saved, "status": desired}),
                "sensor_readback",
            )
        control.state["sensors"][key] = "complete"
        control.save()
    require(
        all(
            v["status"] == (original[n]["status"] if restore else "STOPPED")
            for n, v in current.items()
        ),
        "sensor_transition_incomplete",
    )


def _active_update_run(instance):
    jobs = [job for c in CONTRACTS.values() for job in (c.raw_job, c.silver_job)]
    statement = (
        select(RunsTable.c.run_id)
        .where(
            RunsTable.c.pipeline_name.in_(jobs), RunsTable.c.status.in_(sorted(ACTIVE))
        )
        .limit(1)
    )
    with instance.run_storage.connect() as connection:
        return connection.execute(statement).first()


def idle(instance, control, *, wait=False, sleep=time.sleep):
    started = control.clock()
    while True:
        if not control.read(_active_update_run, instance):
            return
        require(wait and control.clock() - started < 120, "active_update_runs")
        control.state["stage"] = "waiting_for_running_updates"
        control.check()
        sleep(2)
