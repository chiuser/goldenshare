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
    foundation_check = script.index('log "9/12 Foundation 自检"')
    env_load = script.index("load_runtime_env", foundation_check)
    foundation_cli = script.index(".venv/bin/goldenshare list-resources", env_load)
    ops_cli = script.index(".venv/bin/goldenshare ops-reconcile-task-runs", foundation_cli)
    assert foundation_check < env_load < foundation_cli < ops_cli


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


def test_qtf_worker_has_independent_unit_release_commit_and_deploy_lane() -> None:
    layered = (ROOT / "scripts" / "deploy-layered-systemd.sh").read_text(encoding="utf-8")
    wrapper = (ROOT / "scripts" / "deploy-systemd.sh").read_text(encoding="utf-8")
    unit = (ROOT / "scripts" / "goldenshare-qtf-worker.service").read_text(encoding="utf-8")

    assert 'QTF_WORKER_SERVICE="${QTF_WORKER_SERVICE:-goldenshare-qtf-worker.service}"' in layered
    assert 'DEPLOY_QTF="${DEPLOY_QTF:-1}"' in layered
    assert 'QTF_ONLY_MODE="${QTF_ONLY_MODE:-0}"' in layered
    assert 'sync_systemd_unit "${QTF_WORKER_UNIT_SRC}" "${qtf_worker_dst}"' in layered
    assert 'sudo_systemctl enable "${QTF_WORKER_SERVICE}"' in layered
    assert 'sudo_systemctl restart "${QTF_WORKER_SERVICE}"' in layered
    assert "release_commit=\"$(git rev-parse HEAD)\"" in layered
    assert "^[0-9a-f]{40}$" in layered
    assert 'GOLDENSHARE_RELEASE_COMMIT=%s' in layered
    assert "--qtf-only" in wrapper
    assert 'export DEPLOY_FOUNDATION=0' in wrapper
    assert 'export DEPLOY_OPS=0' in wrapper
    assert 'export DEPLOY_PLATFORM=0' in wrapper
    assert 'export RUN_DB_MIGRATION=1' in wrapper
    assert 'export RUN_FRONTEND_BUILD=0' in wrapper
    assert 'EnvironmentFile=-/etc/goldenshare/release.env' in unit
    assert 'ExecStart=/opt/goldenshare/goldenshare/.venv/bin/goldenshare qtf-worker-serve' in unit

    qtf_case_start = wrapper.index("--qtf-only)")
    qtf_case_end = wrapper.index(";;", qtf_case_start)
    qtf_case = wrapper[qtf_case_start:qtf_case_end]
    for disabled in ("DEPLOY_FOUNDATION", "DEPLOY_OPS", "DEPLOY_PLATFORM", "DEPLOY_REALTIME"):
        assert f"export {disabled}=0" in qtf_case
    assert "export DEPLOY_QTF=1" in qtf_case

    qtf_sync_start = layered.index('if [[ "${QTF_ONLY_MODE}" == "1" ]]')
    qtf_sync_end = layered.index("return", qtf_sync_start)
    qtf_sync = layered[qtf_sync_start:qtf_sync_end]
    assert "QTF_WORKER_UNIT_SRC" in qtf_sync
    for unrelated in (
        "WEB_UNIT_SRC",
        "WORKER_UNIT_SRC",
        "SCHEDULER_UNIT_SRC",
        "STK_MINS_WORKER_UNIT_SRC",
        "INDEX_MINS_WORKER_UNIT_SRC",
        "REALTIME_COLLECTOR_UNIT_SRC",
    ):
        assert f"${{{unrelated}}}" not in qtf_sync


def test_sudoers_allows_only_exact_qtf_deploy_commands() -> None:
    sudoers = (ROOT / "scripts" / "goldenshare-deploy.sudoers").read_text(encoding="utf-8")

    for action in ("restart", "status", "enable"):
        assert f"/usr/bin/systemctl {action} goldenshare-qtf-worker.service" in sudoers
    assert (
        "/usr/bin/install -m 644 /opt/goldenshare/goldenshare/scripts/goldenshare-qtf-worker.service "
        "/etc/systemd/system/goldenshare-qtf-worker.service"
    ) in sudoers
    assert (
        "/usr/bin/install -m 644 /opt/goldenshare/goldenshare/.qtf-release.env.next "
        "/etc/goldenshare/release.env.next"
    ) in sudoers
    assert "/usr/bin/mv /etc/goldenshare/release.env.next /etc/goldenshare/release.env" in sudoers
