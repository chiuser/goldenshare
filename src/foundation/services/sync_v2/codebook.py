from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(slots=True, frozen=True)
class SyncCodebookEntry:
    code: str
    label: str
    phase: str | None = None
    suggested_action: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "label": self.label,
            "phase": self.phase,
            "suggested_action": self.suggested_action,
        }


SYNC_CODEBOOK_VERSION: Final[str] = "2026-04-23.v1"
SYNC_CODEBOOK_UPDATED_AT: Final[str] = "2026-04-23T00:00:00Z"

SYNC_ERROR_CODEBOOK: Final[tuple[SyncCodebookEntry, ...]] = (
    SyncCodebookEntry("run_profile_unsupported", "数据集不支持该运行模式", "validator", "检查任务模式与数据集能力"),
    SyncCodebookEntry("invalid_window_for_profile", "时间窗口与运行模式冲突", "validator/planner", "校验 trade_date/start_date/end_date 组合"),
    SyncCodebookEntry("range_required", "缺少时间范围参数", "validator/planner", "补齐开始和结束日期"),
    SyncCodebookEntry("invalid_anchor_type", "锚点类型非法", "validator/planner", "检查 contract 锚点配置"),
    SyncCodebookEntry("source_adapter_not_found", "数据源适配器不存在", "worker/source", "检查 source_key 与适配器注册"),
    SyncCodebookEntry("source_timeout", "上游请求超时", "source", "稍后重试或降低并发"),
    SyncCodebookEntry("source_http_error", "上游 HTTP 异常", "source", "检查状态码和请求参数"),
    SyncCodebookEntry("source_rate_limited", "上游限流", "source", "降频或延后重试"),
    SyncCodebookEntry("source_server_error", "上游服务异常", "source", "稍后重试"),
    SyncCodebookEntry("source_auth_error", "上游鉴权失败", "source", "检查凭据配置"),
    SyncCodebookEntry("payload_invalid", "上游 payload 不合法", "normalize", "检查字段结构与解析逻辑"),
    SyncCodebookEntry("all_rows_rejected", "本批次全部行被拒绝", "normalize", "查看 reason 分布并修正数据或规则"),
    SyncCodebookEntry("dao_not_found", "写入 DAO 路由缺失", "writer", "检查 contract.write_spec 与 DAOFactory 注册"),
    SyncCodebookEntry("write_failed", "写入异常", "writer", "检查数据库约束、冲突策略和目标表结构"),
    SyncCodebookEntry("internal_error", "未归类内部错误", "runtime", "查看完整堆栈定位内部异常"),
    SyncCodebookEntry("dispatcher_error", "调度器执行异常", "runtime", "检查调度执行链路和步骤事件"),
    SyncCodebookEntry("workflow_invalid", "工作流定义异常", "dispatcher", "检查 workflow spec 定义"),
    SyncCodebookEntry("workflow_step_failed", "工作流步骤失败", "dispatcher", "定位失败步骤与上下游依赖"),
    SyncCodebookEntry("execution_failed", "执行失败（统一兜底）", "runtime", "查看 error_message 与运行事件"),
)

SYNC_REASON_CODEBOOK: Final[tuple[SyncCodebookEntry, ...]] = (
    SyncCodebookEntry("normalize.required_field_missing", "必填字段缺失", "normalize", "检查字段映射和空值处理"),
    SyncCodebookEntry("normalize.invalid_date", "日期字段非法", "normalize", "检查日期格式与解析规则"),
    SyncCodebookEntry("normalize.invalid_decimal", "数值字段非法", "normalize", "检查数值格式与精度转换"),
    SyncCodebookEntry("normalize.empty_not_allowed", "非空字段为空", "normalize", "检查空字符串/空白值处理"),
    SyncCodebookEntry("normalize.row_transform_failed", "行转换失败", "normalize", "检查 row_transform 逻辑"),
    SyncCodebookEntry("normalize.payload_invalid", "行内容不符合约束", "normalize", "检查字段类型与结构"),
    SyncCodebookEntry("write.filtered_by_business_rule", "被业务规则过滤", "writer", "检查策略过滤条件"),
    SyncCodebookEntry("write.duplicate_conflict_key_in_batch", "同批次冲突键去重", "writer", "检查批次主键冲突"),
    SyncCodebookEntry("write.target_constraint_filtered", "目标约束导致未写入", "writer", "检查目标表唯一约束/校验规则"),
    SyncCodebookEntry("reason.unknown", "未归类原因", "normalize", "查看样例明细并补充 reason 映射"),
)


def build_sync_codebook_payload() -> dict[str, object]:
    return {
        "version": SYNC_CODEBOOK_VERSION,
        "updated_at": SYNC_CODEBOOK_UPDATED_AT,
        "error_codes": [entry.to_dict() for entry in SYNC_ERROR_CODEBOOK],
        "reason_codes": [entry.to_dict() for entry in SYNC_REASON_CODEBOOK],
    }
