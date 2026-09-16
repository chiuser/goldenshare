"""App-owned single notification loop; no network when credentials are absent."""
import asyncio
from urllib.parse import urlsplit
from src.biz.services.wealth.market.trading_assistant.notification_policy import TradingAssistantNotificationPolicyV1
from src.biz.services.wealth.market.trading_assistant.feishu_transport import FeishuTransport
from src.biz.services.wealth.market.trading_assistant.robot_test_dispatch import RobotTestDispatcher
from src.biz.services.wealth.market.trading_assistant.notification_dispatch import NotificationDispatcher


def resolve_public_base_url(value):
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in {"", "/"}
                or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value):
            return ""
        if url.port is not None and not 1 <= url.port <= 65535:
            return ""
        return "https://" + url.netloc
    except ValueError:
        return ""


async def run_notifications(dependencies, *, stop, logger, transport=None, public_base_url=""):
    if dependencies.robot_commands.store.cipher is None:
        return
    policy = TradingAssistantNotificationPolicyV1()
    transport = transport if transport is not None else FeishuTransport(policy)
    base = resolve_public_base_url(public_base_url)
    if not base:
        try:
            logger.warning("Wealth notification detail address unavailable; formal messages will not be sent")
        except Exception:
            pass
    args = (dependencies.transactions, dependencies.robot_commands.store, transport,
        dependencies.policy, policy, dependencies.now)
    dispatchers = [RobotTestDispatcher(*args), NotificationDispatcher(*args, detail_base_url=base)]
    while not stop.is_set():
        progressed = False
        for dispatcher in dispatchers:
            if stop.is_set():
                break
            try:
                progressed = await dispatcher.tick(cancelled=stop.is_set) or progressed
            except asyncio.CancelledError:
                raise
            except Exception:
                # No exception dump: DB/HTTP exceptions may contain secrets.
                try:
                    logger.warning("trading-assistant notification unit did not complete")
                except Exception:
                    pass
        if progressed:
            await asyncio.sleep(0)
        else:
            try:
                await asyncio.wait_for(stop.wait(), timeout=dependencies.policy.idle_poll_seconds)
            except TimeoutError:
                pass
