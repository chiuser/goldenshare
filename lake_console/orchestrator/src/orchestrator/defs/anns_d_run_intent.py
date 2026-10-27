"""Original announcement asset selection shared by assets and checks."""

import dagster as dg
from dagster._core.snap.execution_plan_snapshot import ExecutionPlanSnapshot

from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_ASSET, AnnouncementError

ASSET_KEY = dg.AssetKey(ANNOUNCEMENT_ASSET)


def _root_snapshot_file_intent(root, instance):
    """Read one original plan when the root's own selection fields are insufficient."""
    snapshot_id = getattr(root, "execution_plan_snapshot_id", None)
    if not snapshot_id:
        raise AnnouncementError("announcement_check_root_intent_unknown")
    snapshot = instance.get_execution_plan_snapshot(snapshot_id)
    if not isinstance(snapshot, ExecutionPlanSnapshot):
        raise AnnouncementError("announcement_check_root_intent_unknown")
    if ASSET_KEY in snapshot.asset_selection:
        return True
    if any(key.asset_key == ASSET_KEY for key in snapshot.asset_check_keys):
        return False
    raise AnnouncementError("announcement_check_root_intent_unknown")


def announcement_root_file_intent(root, *, instance, asset_step_key):
    """Classify the original run without borrowing the current execution subset."""
    selected = getattr(root, "asset_selection", None)
    selected_file = None if selected is None else ASSET_KEY in selected
    steps = getattr(root, "step_keys_to_execute", None)
    if steps is None:
        steps = getattr(root, "resolved_op_selection", None)
    if steps is not None:
        file_step = asset_step_key in steps
        if selected_file is not None and selected_file != file_step:
            return _root_snapshot_file_intent(root, instance)
        if file_step:
            return True
        if selected_file is False:
            return False
        return _root_snapshot_file_intent(root, instance)
    if selected_file is not None:
        return selected_file
    return _root_snapshot_file_intent(root, instance)
