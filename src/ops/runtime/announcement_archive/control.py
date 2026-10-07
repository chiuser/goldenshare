"""Persistent stop/heartbeat with throttled observations outside file commit transactions."""
import threading
import time
from src.foundation.clients.announcement_archive.core import Blocked,Control
from src.foundation.dao.announcement_archive.execution import ExecutionLedger


class WebControl(Control):
    def __init__(self,policy,store,ledger,run):
        super().__init__(policy,emit=lambda _:None)
        self.store,self.ledger,self.run=store,ledger,run
        self.owner=ledger.owner_token;self.fault=None;self.finished=threading.Event()
        self.last_observed=0;self.last_transfer_state=None;self.observation_error=None

    def start(self):
        def monitor():
            last_heartbeat=0
            while not self.finished.wait(self.policy.wait_slice):
                try:
                    refresh=time.monotonic()-last_heartbeat>=self.policy.progress_seconds
                    if self.store.heartbeat(self.run,self.owner,refresh=refresh):self.stop.set()
                    if refresh:last_heartbeat=time.monotonic()
                except Blocked:
                    # A heartbeat write is observation, separate from durable stop/owner facts.
                    try:
                        if self.store.heartbeat(self.run,self.owner,refresh=False):self.stop.set()
                        self.observation_error='archive_observation_failed'
                        if refresh:last_heartbeat=time.monotonic()
                    except Blocked:
                        self.fault='archive_control_failed';self.stop.set();return
        self.thread=threading.Thread(target=monitor,name='archive-stop-heartbeat',daemon=True);self.thread.start()

    def check(self):
        if self.fault:raise Blocked(self.fault)
        try:
            row=self.ledger.run(self.run)
            if row['owner_token']!=self.owner:raise Blocked('archive_owner_changed')
            if row['stop_requested_at']:self.stop.set()
        except Blocked:raise Blocked('archive_control_failed') from None
        super().check()

    def transfer(self,received,total,state):
        self.view.update(bytes_received=received,bytes_total=total)
        if state!=self.last_transfer_state or time.monotonic()-self.last_observed>=self.policy.progress_seconds:
            self._observe(dict(bytes_received=received,bytes_total=total,wait_kind='verifying' if state=='verifying' else None,next_request_at=None))
            self.last_transfer_state=state

    def _observe(self,fields):
        try:
            ExecutionLedger(self.ledger).observe(self.run,fields)
        except Blocked:
            self.observation_error='archive_observation_failed'
            # Business writes and the request_started gate independently verify PG availability.
        finally:self.last_observed=time.monotonic()

    def update(self,**values):
        self.view.update(values)
        if 'waiting' in values:
            reason=self.ledger.cooldown()['reason'] if values['waiting'] else None
            kind=reason if reason in {'interval','backoff','cooldown'} else 'cooldown' if reason in {'http_429','request_end_unknown'} else 'backoff'
            self._observe(dict(wait_kind=kind if values['waiting'] else None,
                               next_request_at=values.get('wait_until') if values['waiting'] else None))

    def close(self):
        self.finished.set()
        if self.thread:self.thread.join(timeout=5)
