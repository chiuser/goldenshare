"""Robot configuration has no retained-input/continue-save workflow."""
import pytest
from pydantic import TypeAdapter, ValidationError

from src.biz.schemas.wealth.market.trading_assistant import recovered_inputs, scopes, robot
from src.biz.services.wealth.market.trading_assistant.write_protocol import parse_scope_key
from tests.test_wealth_trading_assistant_contracts import ID, ID2, operation_fixtures


@pytest.mark.parametrize("operation", ["ROBOT_CANDIDATE_CREATE", "ROBOT_TEST", "ROBOT_CONFIRM"])
def test_robot_input_cannot_be_recovered(operation):
    with pytest.raises(ValidationError):
        TypeAdapter(recovered_inputs.RecoveryInputResponse).validate_python(dict(
            requestId=ID, inputSchemaVersion="1", operationType=operation,
            target=None, input=operation_fixtures()[1][operation]))


def test_robot_is_not_a_recovery_scope():
    with pytest.raises(ValidationError):
        TypeAdapter(scopes.RecoveryScope).validate_python(dict(scopeType="ROBOT"))
    with pytest.raises(ValueError):
        parse_scope_key("ROBOT")


@pytest.mark.parametrize("model,fields", [
    (robot.CandidateCommand, dict(expectedConfigVersionId=None, name="机器人", keywords=[],
        webhook=dict(action="REPLACE", value="private"), signingSecret=dict(action="CLEAR"))),
    (robot.TestCandidateCommand, dict(expectedCandidateVersion="1")),
    (robot.ConfirmCandidateCommand, dict(expectedConfigVersionId=None, testId=ID, receivedConfirmed=True)),
])
def test_commands_have_no_continue_save_version(model, fields):
    payload = dict(requestId=ID, attemptId=ID2, **fields)
    assert model.model_validate(payload)
    with pytest.raises(ValidationError):
        model.model_validate(dict(**payload, expectedRequestStateVersion="1"))
