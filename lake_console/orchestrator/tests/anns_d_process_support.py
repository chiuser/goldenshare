"""Importable spawned workers; they never contact real source resources."""

import json
import os
import time


def successful_worker(token, params, output, signal):
    from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_FIELDS

    with open(output, "x") as stream:
        json.dump({"columns": ANNOUNCEMENT_FIELDS, "rows": []}, stream)
    signal.send("ok")


def sleeping_worker(token, params, output, signal):
    time.sleep(60)


def exited_worker(token, params, output, signal):
    os._exit(7)
