from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_enables_date_completeness_worker_for_ops_layer() -> None:
    script = (ROOT / "scripts" / "deploy-layered-systemd.sh").read_text(encoding="utf-8")
    unit = (ROOT / "scripts" / "goldenshare-date-completeness-worker.service").read_text(encoding="utf-8")

    ops_case_start = script.index("    ops)")
    ops_case_end = script.index("    platform)", ops_case_start)
    ops_case = script[ops_case_start:ops_case_end]

    enable = ops_case.index('sudo_systemctl enable "${DATE_COMPLETENESS_WORKER_SERVICE}"')
    restart = ops_case.index('sudo_systemctl restart "${DATE_COMPLETENESS_WORKER_SERVICE}"')
    assert enable < restart
    assert "[Install]" in unit
    assert "WantedBy=multi-user.target" in unit


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


def test_sudoers_allows_date_completeness_worker_autostart() -> None:
    sudoers = (ROOT / "scripts" / "goldenshare-deploy.sudoers").read_text(encoding="utf-8")

    assert "/usr/bin/systemctl restart goldenshare-date-completeness-worker.service" in sudoers
    assert "/usr/bin/systemctl status goldenshare-date-completeness-worker.service" in sudoers
    assert "/usr/bin/systemctl enable goldenshare-date-completeness-worker.service" in sudoers


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
    dependency_install = main_body.index('.venv/bin/pip install ./packages/technical_indicators -e "${PIP_INSTALL_TARGET}"')
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


@pytest.fixture
def deployment(tmp_path: Path):
    """Run both real scripts; replace deployment I/O, keep configuration Python real."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for source in [ROOT / "scripts" / name for name in ("deploy-systemd.sh", "deploy-layered-systemd.sh")]:
        shutil.copy2(source, scripts / source.name)
        (scripts / source.name).chmod(0o755)
    for source in (ROOT / "scripts").glob("goldenshare-*.service"):
        shutil.copy2(source, scripts / source.name)
    repo = tmp_path / "repo"
    binaries = repo / ".venv" / "bin"
    binaries.mkdir(parents=True)
    for name in ("frontend", "wealth", "units"):
        (repo / name).mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "commands.log"

    def executable(path, body):
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body, encoding="utf-8")
        path.chmod(0o755)

    executable(fake_bin / "git", 'echo "git $*" >> "$DEPLOY_TEST_LOG"\n')
    executable(fake_bin / "flock", "exit 0\n")
    executable(fake_bin / "curl", "exit 0\n")
    executable(fake_bin / "npm", 'echo "npm $*" >> "$DEPLOY_TEST_LOG"\n')
    executable(fake_bin / "systemctl", '''echo "systemctl $*" >> "$DEPLOY_TEST_LOG"
if [[ "$1" == "cat" ]]; then echo 'ExecStart=python -m src.app.web.run'; fi
''')
    executable(fake_bin / "sudo", '''if [[ "$1" == "-n" ]]; then shift; fi
if [[ "$1" == "-l" ]]; then exit 0; fi
echo "sudo $*" >> "$DEPLOY_TEST_LOG"
"$@"
''')
    executable(binaries / "pip", '''echo "pip $*" >> "$DEPLOY_TEST_LOG"
exit "${DEPLOY_TEST_INSTALL_STATUS:-0}"
''')
    executable(binaries / "goldenshare", 'echo "cli $*" >> "$DEPLOY_TEST_LOG"\n')
    # The shim runs the script's actual stdin, never substitutes a success result.
    # The negative contract reproduces the real pre-a74374cc3 package field.
    executable(binaries / "python", f'''echo "python config-check" >> "$DEPLOY_TEST_LOG"
exec "{sys.executable}" -c '
import os, sys
if os.environ.get("DEPLOY_TEST_OLD_CONFIG") == "1":
    from dataclasses import make_dataclass
    import src.foundation.config.settings as settings
    settings.KernelConfig = make_dataclass("KernelConfig", [
        ("goldenshare_lake_root", str), ("max_output_bytes", int),
    ])
exec(compile(sys.stdin.read(), "<deploy-config-check>", "exec"))
' "$@"
''')
    env_file = tmp_path / "runtime.env"
    env_file.write_text("TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS=5\n", encoding="utf-8")
    inherited_env = tmp_path / "inherited.env"
    inherited_env.write_text("TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS=501\n", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "REPO_DIR": str(repo), "ENV_FILE": str(env_file),
        "GOLDENSHARE_ENV_FILE": str(inherited_env),
        "DEPLOY_TEST_LOG": str(log), "DEPLOY_LOCK_FILE": str(tmp_path / "deploy.lock"),
        "SYSTEMCTL_BIN": str(fake_bin / "systemctl"), "SYSTEMD_UNIT_DIR": str(repo / "units"),
        "DEPLOY_FOUNDATION": "1", "DEPLOY_OPS": "1", "DEPLOY_PLATFORM": "1",
        "DEPLOY_REALTIME": "1", "DEPLOY_QTF": "1", "QTF_ONLY_MODE": "0",
        "MAINTENANCE_MIGRATION_MODE": "0", "RUN_DB_MIGRATION": "1",
        "RUN_FRONTEND_BUILD": "1", "RUN_WEALTH_BUILD": "1", "RUN_SYNC_UNITS": "0",
        "RUN_DEFAULT_SINGLE_SOURCE_SEED": "0", "RUN_MONEYFLOW_MULTI_SOURCE_SEED": "0",
        "PIP_INSTALL_TARGET": ".",
    }

    def run(*options, extra_env=None):
        result = subprocess.run(
            ["bash", str(scripts / "deploy-systemd.sh"), "dev-interface", *options],
            capture_output=True, text=True, check=False, env={**env, **(extra_env or {})},
        )
        return result, log.read_text(encoding="utf-8").splitlines()

    return run, env_file


@pytest.mark.parametrize("mode,restarted", [
    ((), {"web", "ops-worker", "ops-scheduler", "date-completeness-worker", "ops-task-completion-worker",
          "ops-stk-mins-worker", "ops-index-mins-worker", "qtf-worker", "realtime-collector"}),
    (("--platform-only",), {"web"}),
    (("--ops-only",), {"ops-worker", "ops-scheduler", "date-completeness-worker",
                       "ops-task-completion-worker", "ops-stk-mins-worker", "ops-index-mins-worker"}),
    (("--foundation-only",), {"ops-worker", "ops-task-completion-worker", "ops-stk-mins-worker", "ops-index-mins-worker"}),
    (("--qtf-only",), {"qtf-worker"}),
    (("--maintenance-migration",), set()),
])
def test_one_command_installs_package_and_checks_before_mutations(deployment, mode, restarted):
    run, _ = deployment
    result, commands = run(*mode)
    assert result.returncode == 0, result.stdout + result.stderr
    install = commands.index("pip install ./packages/technical_indicators -e .")
    check = commands.index("python config-check")
    assert install < check < commands.index("cli init-db")
    assert sum(line.startswith("pip ") for line in commands) == 1
    for index, line in enumerate(commands):
        if line.startswith(("npm ", "sudo install ", "systemctl daemon-reload", "systemctl restart ")):
            assert check < index
    assert "技术指标包版本=0.1.0，路径=" in result.stdout
    assert "技术指标包与主工程配置校验通过" in result.stdout
    assert {line.removeprefix("systemctl restart ") for line in commands if line.startswith("systemctl restart ")} == {
        f"goldenshare-{name}.service" for name in restarted
    }
    if mode == ("--maintenance-migration",):
        assert not any(line.startswith(("npm ", "sudo ", "systemctl ")) for line in commands)


@pytest.mark.parametrize("options,target", [
    (("--with-dev-deps",), ".[dev]"),
    (("--pip-install-target", ".[local-lake]"), ".[local-lake]"),
])
def test_install_preserves_existing_target_options(deployment, options, target):
    run, _ = deployment
    result, commands = run("--platform-only", *options)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"pip install ./packages/technical_indicators -e {target}" in commands


@pytest.mark.parametrize("failure,status,environment,message", [
    ("install", 23, {"DEPLOY_TEST_INSTALL_STATUS": "23"}, ""),
    ("old-package", 1, {"DEPLOY_TEST_OLD_CONFIG": "1"}, "technical_indicator_max_output_bytes"),
    ("invalid-config", 1, {}, "TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS"),
])
def test_install_or_real_config_failure_stops_before_mutations(deployment, failure, status, environment, message):
    run, env_file = deployment
    if failure == "invalid-config":
        env_file.write_text("TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS=501\n", encoding="utf-8")
    result, commands = run(extra_env=environment)
    assert result.returncode == status, result.stdout + result.stderr
    assert message in result.stderr
    assert not any(line.startswith(("npm ", "cli ", "sudo ", "systemctl ")) for line in commands)
    assert ("python config-check" in commands) == (failure != "install")
    assert "技术指标包与主工程配置校验通过" not in result.stdout
    if failure == "old-package":
        assert "AttributeError" in result.stderr
