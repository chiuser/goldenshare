"""Read current safe display metadata without reading encrypted secrets."""
from sqlalchemy import select
from src.biz.models.wealth.trading_assistant.rules import RobotIdentity
from src.biz.models.wealth.trading_assistant.robots import RobotConfig
from src.biz.schemas.wealth.market.trading_assistant.robot import RobotResponse, RobotConfig as ConfigDto
from src.biz.services.wealth.market.trading_assistant.robot_configuration import RobotConfigurationStore
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget


class RobotConfigurationQuery:
    def __init__(self, policy):
        self.policy = policy

    def read(self, session, *, owner_id, deadline):
        apply_sql_budget(session, deadline, self.policy)
        row = session.scalar(select(RobotConfig).join(RobotIdentity,
            (RobotIdentity.owner_user_id == RobotConfig.owner_user_id) &
            (RobotIdentity.robot_id == RobotConfig.robot_id) &
            (RobotIdentity.current_config_id == RobotConfig.config_id)).where(RobotIdentity.owner_user_id == owner_id))
        deadline.remaining_ms()
        return RobotResponse(robot=None if row is None else ConfigDto(robotId=str(row.robot_id),
            configVersionId=str(row.config_id), **RobotConfigurationStore._display(row)))
