from __future__ import annotations

import os
import subprocess
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


def test_maintenance_migration_lane_cannot_restart_or_seed_services() -> None:
    wrapper = (ROOT / "scripts" / "deploy-systemd.sh").read_text(encoding="utf-8")
    layered = (ROOT / "scripts" / "deploy-layered-systemd.sh").read_text(encoding="utf-8")

    assert "--maintenance-migration" in wrapper
    mode_start = wrapper.index('if [[ "${MAINTENANCE_MIGRATION_MODE}" == "1" ]]')
    mode_end = wrapper.index('elif [[ "${QTF_ONLY_MODE}" == "1" ]]', mode_start)
    mode = wrapper[mode_start:mode_end]

    for disabled in (
        "DEPLOY_FOUNDATION",
        "DEPLOY_OPS",
        "DEPLOY_PLATFORM",
        "DEPLOY_REALTIME",
        "DEPLOY_QTF",
        "RUN_FRONTEND_BUILD",
        "RUN_WEALTH_BUILD",
        "RUN_DEFAULT_SINGLE_SOURCE_SEED",
        "RUN_MONEYFLOW_MULTI_SOURCE_SEED",
        "RUN_SYNC_UNITS",
    ):
        assert f"export {disabled}=0" in mode
    assert "export RUN_DB_MIGRATION=1" in mode
    assert "export MAINTENANCE_MIGRATION_MODE=1" in mode
    assert "不负责暂停 schedule 或停止服务" in mode
    assert '--maintenance-migration 不能与 --qtf-only 同时使用' in wrapper
    assert 'MAINTENANCE_MIGRATION_MODE="${MAINTENANCE_MIGRATION_MODE:-0}"' in layered
    assert 'if [[ "${MAINTENANCE_MIGRATION_MODE}" != "1" ]]; then\n    ensure_sudo_ready' in layered
    assert '维护迁移模式：保持 systemd 与全部服务当前状态' in layered
    assert '维护迁移模式：跳过 Ops 状态协调、Web 健康检查和服务状态读取' in layered
    assert '服务仍保持调用前状态，必须由维护流程单独验收并恢复' in layered


def test_maintenance_migration_lane_exports_safe_effective_contract(tmp_path: Path) -> None:
    wrapper = tmp_path / "deploy-systemd.sh"
    layered = tmp_path / "deploy-layered-systemd.sh"
    wrapper.write_text((ROOT / "scripts" / "deploy-systemd.sh").read_text(encoding="utf-8"), encoding="utf-8")
    layered.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\\n' \\
  "branch=$1" \\
  "foundation=${DEPLOY_FOUNDATION}" \\
  "ops=${DEPLOY_OPS}" \\
  "platform=${DEPLOY_PLATFORM}" \\
  "realtime=${DEPLOY_REALTIME}" \\
  "qtf=${DEPLOY_QTF}" \\
  "migration=${RUN_DB_MIGRATION}" \\
  "frontend=${RUN_FRONTEND_BUILD}" \\
  "wealth=${RUN_WEALTH_BUILD}" \\
  "default_seed=${RUN_DEFAULT_SINGLE_SOURCE_SEED}" \\
  "moneyflow_seed=${RUN_MONEYFLOW_MULTI_SOURCE_SEED}" \\
  "sync_units=${RUN_SYNC_UNITS}" \\
  "maintenance=${MAINTENANCE_MIGRATION_MODE}"
""",
        encoding="utf-8",
    )
    layered.chmod(0o755)

    result = subprocess.run(
        ["bash", str(wrapper), "dev-interface", "--maintenance-migration"],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DEPLOY_FOUNDATION": "1",
            "DEPLOY_OPS": "1",
            "DEPLOY_PLATFORM": "1",
            "DEPLOY_REALTIME": "1",
            "DEPLOY_QTF": "1",
            "RUN_DB_MIGRATION": "0",
            "RUN_FRONTEND_BUILD": "1",
            "RUN_WEALTH_BUILD": "1",
            "RUN_DEFAULT_SINGLE_SOURCE_SEED": "1",
            "RUN_MONEYFLOW_MULTI_SOURCE_SEED": "1",
            "RUN_SYNC_UNITS": "1",
        },
    )

    assert result.stdout.splitlines() == [
        "branch=dev-interface",
        "foundation=0",
        "ops=0",
        "platform=0",
        "realtime=0",
        "qtf=0",
        "migration=1",
        "frontend=0",
        "wealth=0",
        "default_seed=0",
        "moneyflow_seed=0",
        "sync_units=0",
        "maintenance=1",
    ]


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
    assert "release.env" not in layered
    assert "GOLDENSHARE_RELEASE_COMMIT" not in layered
    assert "--qtf-only" in wrapper
    assert 'export DEPLOY_FOUNDATION=0' in wrapper
    assert 'export DEPLOY_OPS=0' in wrapper
    assert 'export DEPLOY_PLATFORM=0' in wrapper
    assert 'export RUN_DB_MIGRATION=1' in wrapper
    assert 'export RUN_FRONTEND_BUILD=0' in wrapper
    assert 'ExecStart=/opt/goldenshare/goldenshare/.venv/bin/goldenshare qtf-worker-serve' in unit
    assert "User=goldenshare" in unit
    assert "Group=goldenshare" in unit
    assert "EnvironmentFile=" not in unit

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
    assert "release.env" not in sudoers
    assert "/usr/bin/mv" not in sudoers


def test_qtf_sudo_permissions_are_checked_before_any_deploy_mutation() -> None:
    script = (ROOT / "scripts" / "deploy-layered-systemd.sh").read_text(encoding="utf-8")
    main_start = script.index("main() {")
    main_body = script[main_start:]

    qtf_preflight = main_body.index("ensure_qtf_sudo_ready")
    lock = main_body.index("acquire_deploy_lock")
    git_fetch = main_body.index("git fetch --all --prune")
    dependency_install = main_body.index('.venv/bin/pip install -e "${PIP_INSTALL_TARGET}"')
    migration = main_body.index('.venv/bin/goldenshare init-db')

    assert qtf_preflight < lock < git_fetch < dependency_install < migration
    for command in (
        'check_sudo_permission /usr/bin/install -m 644 "${QTF_WORKER_UNIT_SRC}" "${qtf_worker_dst}"',
        'check_sudo_permission "${SYSTEMCTL_BIN}" daemon-reload',
        'check_sudo_permission "${SYSTEMCTL_BIN}" enable "${QTF_WORKER_SERVICE}"',
        'check_sudo_permission "${SYSTEMCTL_BIN}" restart "${QTF_WORKER_SERVICE}"',
        'check_sudo_permission "${SYSTEMCTL_BIN}" status "${QTF_WORKER_SERVICE}"',
    ):
        assert command in script


def test_missing_qtf_sudo_permission_fails_before_git_or_lock(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git_marker = tmp_path / "git-called"
    fake_git = fake_bin / "git"
    fake_git.write_text(f'#!/usr/bin/env bash\ntouch "{git_marker}"\n', encoding="utf-8")
    fake_git.chmod(0o755)
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_sudo.chmod(0o755)
    fake_systemctl = fake_bin / "systemctl"
    fake_systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)
    lock_file = tmp_path / "deploy.lock"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "DEPLOY_QTF": "1",
            "RUN_FRONTEND_BUILD": "0",
            "RUN_WEALTH_BUILD": "0",
            "REPO_DIR": str(tmp_path / "repo"),
            "DEPLOY_LOCK_FILE": str(lock_file),
            "SYSTEMCTL_BIN": str(fake_systemctl),
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "deploy-layered-systemd.sh"), "dev-interface"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "QTF 部署缺少以上无密码 sudo 精确权限" in result.stdout
    assert "尚未拉代码、安装依赖、构建、迁移或重启服务" in result.stdout
    assert "password is required" not in (result.stdout + result.stderr)
    assert not git_marker.exists()
    assert not lock_file.exists()
