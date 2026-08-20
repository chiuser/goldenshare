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


def test_deploy_script_manages_both_minute_workers_for_foundation_or_ops_layers() -> None:
    script = (ROOT / "scripts" / "deploy-layered-systemd.sh").read_text(encoding="utf-8")

    for service, source_name in (
        ("goldenshare-ops-stk-mins-worker.service", "STK_MINS_WORKER"),
        ("goldenshare-ops-index-mins-worker.service", "INDEX_MINS_WORKER"),
    ):
        assert f'{source_name}_SERVICE="${{{source_name}_SERVICE:-{service}}}"' in script
        assert f'{source_name}_UNIT_SRC="${{{source_name}_UNIT_SRC:-${{SCRIPT_DIR}}/{service}}}"' in script
        assert f'sudo_systemctl enable "${{{source_name}_SERVICE}}"' in script
        assert f'sudo_systemctl restart "${{{source_name}_SERVICE}}"' in script
        assert f'print_service_status "${{{source_name}_SERVICE}}"' in script

    assert "restart_minute_workers_if_needed" in script
    assert 'DEPLOY_FOUNDATION}" == "1" || "${DEPLOY_OPS}' in script
    assert 'DEPLOY_FOUNDATION}" != "1" && "${DEPLOY_OPS}" == "1"' in script
    assert 'sudo_systemctl restart "${WORKER_SERVICE}"' in script


def test_deploy_script_loads_runtime_env_before_cli_self_checks() -> None:
    script = (ROOT / "scripts" / "deploy-layered-systemd.sh").read_text(encoding="utf-8")

    assert "load_runtime_env() {" in script
    assert (
        'log "9/12 Foundation 自检"\n'
        "  load_runtime_env\n"
        "  .venv/bin/goldenshare list-resources >/dev/null\n"
        "\n"
        '  log "10/12 Ops 自检"\n'
        "  .venv/bin/goldenshare ops-reconcile-task-runs >/dev/null"
    ) in script


def test_sudoers_allows_task_completion_worker_deploy_commands() -> None:
    sudoers = (ROOT / "scripts" / "goldenshare-deploy.sudoers").read_text(encoding="utf-8")

    assert "/usr/bin/systemctl restart goldenshare-ops-task-completion-worker.service" in sudoers
    assert "/usr/bin/systemctl status goldenshare-ops-task-completion-worker.service" in sudoers
    assert "/usr/bin/systemctl enable goldenshare-ops-task-completion-worker.service" in sudoers
    assert (
        "/usr/bin/install -m 644 /opt/goldenshare/goldenshare/scripts/goldenshare-ops-task-completion-worker.service "
        "/etc/systemd/system/goldenshare-ops-task-completion-worker.service"
    ) in sudoers


def test_sudoers_allows_both_minute_worker_deploy_commands() -> None:
    sudoers = (ROOT / "scripts" / "goldenshare-deploy.sudoers").read_text(encoding="utf-8")

    for service in ("goldenshare-ops-stk-mins-worker.service", "goldenshare-ops-index-mins-worker.service"):
        assert f"/usr/bin/systemctl restart {service}" in sudoers
        assert f"/usr/bin/systemctl status {service}" in sudoers
        assert f"/usr/bin/systemctl enable {service}" in sudoers
        assert (
            f"/usr/bin/install -m 644 /opt/goldenshare/goldenshare/scripts/{service} "
            f"/etc/systemd/system/{service}"
        ) in sudoers
