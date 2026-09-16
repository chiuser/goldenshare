"""One in-process IO slot; concrete stores own durable claim and finish."""
import asyncio
from .execution_policy import Deadline
from .credential_cipher import CredentialError
from .feishu_protocol import FeishuInputError, SendOutcome


class DurableMessageDispatcher:
    def __init__(self, transactions, store, transport, policy, notification_policy, now):
        self.transactions, self.store, self.transport = transactions, store, transport
        self.policy, self.notification_policy, self.now = policy, notification_policy, now
        self._slot = asyncio.Lock()

    async def tick(self, *, cancelled=lambda: False):
        async with self._slot:
            if cancelled():
                return False
            deadline = Deadline.after_ms(self.policy.batch_budget_ms)
            await self.transactions.run(lambda s: self._sweep(s, deadline), deadline=deadline, write=True)
            if cancelled():
                return False
            deadline = Deadline.after_ms(self.policy.batch_budget_ms)
            claim = await self.transactions.run(lambda s: self._claim(s, deadline), deadline=deadline, write=True)
            if claim is None:
                return False
            identity, token = claim
            try:
                deadline = Deadline.after_ms(self.policy.batch_budget_ms)
                prepared = await self.transactions.run(lambda s: self._payload(s, identity, token, deadline),
                    deadline=deadline, write=False)
                if prepared is None:
                    return True
                if cancelled():
                    outcome = SendOutcome("FAILED", "本次消息尚未发送")
                else:
                    outcome = await self.transport.send(*prepared)
            except (CredentialError, FeishuInputError):
                outcome = SendOutcome("FAILED", "机器人凭据或消息校验未通过，本次消息未发送")
            # Unexpected failure/cancellation leaves a durable claim. Only its
            # original sender may finish; the next sweep never resends it.
            deadline = Deadline.after_ms(self.policy.batch_budget_ms)
            await self.transactions.run(lambda s: self._finish(s, identity, token, outcome, deadline),
                deadline=deadline, write=True)
            return True
