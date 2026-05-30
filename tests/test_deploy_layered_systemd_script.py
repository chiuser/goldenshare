from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_manages_task_completion_worker_for_foundation_or_ops_layers() -> None:
    script = (ROOT / "scripts" / "deploy-layered-systemd.sh").read_text(encoding="utf-8")

    assert 'TASK_COMPLETION_WORKER_SERVICE="${TASK_COMPLETION_WORKER_SERVICE:-goldenshare-ops-task-completion-worker.service}"' in script
    assert 'TASK_COMPLETION_WORKER_UNIT_SRC="${TASK_COMPLETION_WORKER_UNIT_SRC:-${SCRIPT_DIR}/goldenshare-ops-task-completion-worker.service}"' in script
    assert 'sync_systemd_unit "${TASK_COMPLETION_WORKER_UNIT_SRC}" "${task_completion_worker_dst}"' in script
    assert 'if [[ "${DEPLOY_FOUNDATION}" == "1" || "${DEPLOY_OPS}" == "1" ]]; then' in script
    assert 'sudo_systemctl enable "${TASK_COMPLETION_WORKER_SERVICE}"' in script
    assert 'sudo_systemctl restart "${TASK_COMPLETION_WORKER_SERVICE}"' in script
    assert 'print_service_status "${TASK_COMPLETION_WORKER_SERVICE}"' in script


def test_sudoers_allows_task_completion_worker_deploy_commands() -> None:
    sudoers = (ROOT / "scripts" / "goldenshare-deploy.sudoers").read_text(encoding="utf-8")

    assert "/usr/bin/systemctl restart goldenshare-ops-task-completion-worker.service" in sudoers
    assert "/usr/bin/systemctl status goldenshare-ops-task-completion-worker.service" in sudoers
    assert "/usr/bin/systemctl enable goldenshare-ops-task-completion-worker.service" in sudoers
    assert (
        "/usr/bin/install -m 644 /opt/goldenshare/goldenshare/scripts/goldenshare-ops-task-completion-worker.service "
        "/etc/systemd/system/goldenshare-ops-task-completion-worker.service"
    ) in sudoers
