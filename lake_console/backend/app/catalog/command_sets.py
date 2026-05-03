from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeCommandExample, LakeCommandSetDefinition


LAKE_COMMAND_SETS: tuple[LakeCommandSetDefinition, ...] = (
    LakeCommandSetDefinition(
        command_set_key="lake_maintenance",
        display_name="Lake 维护命令",
        group_key="maintenance",
        description="本地 Lake Root 初始化、状态查看、数据集扫描与临时目录清理命令。",
        command_examples=(
            LakeCommandExample(
                example_key="lake_init",
                title="初始化 Lake Root",
                scenario="init",
                description="创建本地 Lake Root 基础目录结构。",
                argv=("lake-console", "init"),
                prerequisites=("已在配置文件或环境变量中设置 GOLDENSHARE_LAKE_ROOT。",),
            ),
            LakeCommandExample(
                example_key="lake_status",
                title="查看 Lake Root 状态",
                scenario="status",
                description="检查路径、容量、配置等基础状态。",
                argv=("lake-console", "status"),
            ),
            LakeCommandExample(
                example_key="lake_list_datasets",
                title="列出本地数据集",
                scenario="diagnostic",
                description="扫描当前 Lake Root 下已经落盘的数据集。",
                argv=("lake-console", "list-datasets"),
            ),
            LakeCommandExample(
                example_key="lake_clean_tmp_dry_run",
                title="预览临时目录清理",
                scenario="maintenance",
                description="只列出可清理的 _tmp run 目录，不删除。",
                argv=("lake-console", "clean-tmp", "--dry-run"),
            ),
            LakeCommandExample(
                example_key="lake_clean_tmp_old_runs",
                title="清理旧临时目录",
                scenario="maintenance",
                description="清理超过指定小时数的 _tmp run 目录。",
                argv=("lake-console", "clean-tmp", "--older-than-hours", "24"),
            ),
        ),
    ),
)

_COMMAND_SET_BY_KEY = {command_set.command_set_key: command_set for command_set in LAKE_COMMAND_SETS}


def get_command_set(command_set_key: str) -> LakeCommandSetDefinition:
    try:
        return _COMMAND_SET_BY_KEY[command_set_key]
    except KeyError as exc:
        raise ValueError(f"Unknown Lake command set: {command_set_key}") from exc


def list_command_sets() -> tuple[LakeCommandSetDefinition, ...]:
    return LAKE_COMMAND_SETS
