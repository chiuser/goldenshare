"""Fair coordination of TA units, without owning a thread or database Session."""
import asyncio


async def run_calculation_loop(run_one, *, policy, stop, logger):
    while not stop.is_set():
        progressed = False
        for kind in ("CALCULATE", "CUTOFF", "HISTORY"):
            if stop.is_set():
                return
            try:
                stage = await run_one(kind)
            except asyncio.CancelledError:
                # The resource owner still has to drain the underlying thread.
                raise
            except Exception:
                # A logging sink must not kill the business coordinator. Do
                # not include raw exceptions or private source/account inputs.
                try:
                    logger.warning("trading-assistant bounded execution unit did not complete: %s", kind)
                except Exception:
                    pass
            else:
                progressed |= stage not in ("IDLE", "UNCHANGED", "WAITING_DATA", "FAILED", "TRANSIENT", "SUPERSEDED")
            if stop.is_set():
                return
            await asyncio.sleep(0)
        if not progressed:
            try:
                await asyncio.wait_for(stop.wait(), timeout=policy.idle_poll_seconds)
            except TimeoutError:
                pass
