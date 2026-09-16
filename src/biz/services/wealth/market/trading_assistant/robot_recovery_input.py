"""Bind original route identity to safe retained input; never send or replay."""
from uuid import UUID

from src.biz.schemas.wealth.market.trading_assistant.robot import TestCandidateCommand, ConfirmCandidateCommand
from src.biz.schemas.wealth.market.trading_assistant.recovered_inputs import RobotTestRecoveryInput, RobotConfirmRecoveryInput

RECOVERY_MODELS = {"ROBOT_TEST": RobotTestRecoveryInput, "ROBOT_CONFIRM": RobotConfirmRecoveryInput}
COMMAND_MODELS = {"ROBOT_TEST": TestCandidateCommand, "ROBOT_CONFIRM": ConfirmCandidateCommand}


def bind_robot_candidate(operation, *, candidate_id: UUID, command):
    """Called with the parsed HTTP path, not a candidate supplied in JSON."""
    if operation not in COMMAND_MODELS or not isinstance(candidate_id, UUID):
        raise ValueError("Invalid robot operation identity")
    if not isinstance(command, COMMAND_MODELS[operation]):
        raise ValueError("Wrong command for robot operation")
    values = command.model_dump(mode="json", exclude={"requestId", "attemptId", "expectedRequestStateVersion"})
    return RECOVERY_MODELS[operation].model_validate(dict(**values, candidateId=str(candidate_id))).model_dump(mode="json")
