from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(slots=True, frozen=True)
class IngestionCodebookEntry:
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


INGESTION_CODEBOOK_VERSION: Final[str] = "2026-04-26.v1"
INGESTION_CODEBOOK_UPDATED_AT: Final[str] = "2026-04-26T00:00:00Z"

INGESTION_ERROR_CODEBOOK: Final[tuple[IngestionCodebookEntry, ...]] = (
    IngestionCodebookEntry("dataset_mismatch", "请求数据集与定义不一致", "validator", "检查 dataset_key 与定义绑定"),
    IngestionCodebookEntry("run_profile_unsupported", "数据集不支持该运行模式", "validator", "检查任务模式与数据集能力"),
    IngestionCodebookEntry("time_anchor_not_allowed", "当前模式不允许时间锚点参数", "validator", "移除不允许的时间参数"),
    IngestionCodebookEntry("invalid_window_for_profile", "时间窗口与运行模式冲突", "validator/planner", "校验时间窗口组合"),
    IngestionCodebookEntry("range_not_allowed", "当前模式不允许区间参数", "validator", "移除 start_date/end_date 或切换为区间模式"),
    IngestionCodebookEntry("missing_anchor_fields", "缺少锚点必填参数", "validator", "补齐 trade_date/month 等锚点参数"),
    IngestionCodebookEntry("range_required", "缺少时间范围参数", "validator/planner", "补齐开始和结束日期"),
    IngestionCodebookEntry("invalid_range", "时间范围非法", "validator", "确保 start_date <= end_date"),
    IngestionCodebookEntry("required_param_missing", "缺少必填参数", "validator", "补齐 required 参数"),
    IngestionCodebookEntry("unknown_params", "存在未定义参数", "validator", "移除不在 input schema 中的参数"),
    IngestionCodebookEntry("required_group_unsatisfied", "必选参数组未满足", "validator", "在必选组中至少填写一个参数"),
    IngestionCodebookEntry("mutually_exclusive_violation", "互斥参数同时出现", "validator", "仅保留互斥组中的一个参数"),
    IngestionCodebookEntry("dependency_violation", "参数依赖关系不满足", "validator", "补齐依赖参数"),
    IngestionCodebookEntry("invalid_date", "日期参数格式非法", "validator", "使用 YYYYMMDD 或 YYYY-MM-DD"),
    IngestionCodebookEntry("invalid_integer", "整数参数格式非法", "validator", "检查参数类型并传入整数"),
    IngestionCodebookEntry("invalid_boolean", "布尔参数格式非法", "validator", "使用 true/false 或 1/0"),
    IngestionCodebookEntry("invalid_enum", "枚举参数值非法", "validator", "改为定义允许的枚举值"),
    IngestionCodebookEntry("forbidden_sentinel", "请求参数包含禁用哨兵值", "validator/planner/normalize", "使用真实枚举值，不允许使用 ALL 哨兵值"),
    IngestionCodebookEntry("empty_not_allowed", "参数不允许为空", "validator", "填写非空值"),
    IngestionCodebookEntry("invalid_month_key", "月份参数格式非法", "validator", "使用 YYYYMM 或 YYYY-MM"),
    IngestionCodebookEntry("invalid_anchor_type", "锚点类型非法", "validator/planner", "检查 date model 与输入形状"),
    IngestionCodebookEntry("units_exceeded", "执行单元数量超出限制", "planner", "缩小时间窗口或调整 unit 上限"),
    IngestionCodebookEntry("fanout_missing", "分片参数缺失且无默认值", "planner", "补齐 fanout 参数或配置默认值"),
    IngestionCodebookEntry("trade_date_anchor_required", "缺少交易日锚点", "planner", "补齐 trade_date 或 start/end 区间"),
    IngestionCodebookEntry("universe_empty", "规划范围为空", "planner", "检查股票池/板块池或上游基础数据"),
    IngestionCodebookEntry("unknown_universe_policy", "未知的规划范围策略", "planner", "检查 planning.universe_policy 配置"),
    IngestionCodebookEntry("request_builder_not_found", "请求参数构造器不存在", "planner", "检查 source.request_builder_key 与注册函数"),
    IngestionCodebookEntry("source_adapter_not_found", "数据源适配器不存在", "source", "检查 source_key 与适配器映射"),
    IngestionCodebookEntry("source_timeout", "上游请求超时", "source", "稍后重试或降低并发"),
    IngestionCodebookEntry("source_http_error", "上游 HTTP 异常", "source", "检查状态码和请求参数"),
    IngestionCodebookEntry("source_rate_limited", "上游限流", "source", "降频或延后重试"),
    IngestionCodebookEntry("source_server_error", "上游服务异常", "source", "稍后重试"),
    IngestionCodebookEntry("source_auth_error", "上游鉴权失败", "source", "检查凭据配置"),
    IngestionCodebookEntry("payload_invalid", "上游 payload 不合法", "normalize", "检查字段结构与解析逻辑"),
    IngestionCodebookEntry("all_rows_rejected", "本批次全部行被拒绝", "normalize", "查看 reason 分布并修正数据或规则"),
    IngestionCodebookEntry("dao_not_found", "写入 DAO 路由缺失", "writer", "检查 storage.write_path 与 DAOFactory 注册"),
    IngestionCodebookEntry("write_failed", "写入异常", "writer", "检查数据库约束、冲突策略和目标表结构"),
    IngestionCodebookEntry("internal_error", "未归类内部错误", "runtime", "查看完整堆栈定位内部异常"),
    IngestionCodebookEntry("dispatcher_error", "调度器执行异常", "runtime", "检查任务调度链路和步骤事件"),
    IngestionCodebookEntry("worker_finalize_error", "执行收尾阶段异常", "runtime", "检查任务终态写入和快照刷新链路"),
    IngestionCodebookEntry("workflow_invalid", "工作流定义异常", "dispatcher", "检查 workflow spec 定义"),
    IngestionCodebookEntry("workflow_step_failed", "工作流步骤失败", "dispatcher", "定位失败步骤与上下游依赖"),
    IngestionCodebookEntry("ingestion_failed", "维护执行失败（统一兜底）", "runtime", "查看 error_message 与运行事件"),
)

INGESTION_REASON_CODEBOOK: Final[tuple[IngestionCodebookEntry, ...]] = (
    IngestionCodebookEntry("normalize.required_field_missing", "必填字段缺失", "normalize", "检查字段映射和空值处理"),
    IngestionCodebookEntry("normalize.invalid_date", "日期字段非法", "normalize", "检查日期格式与解析规则"),
    IngestionCodebookEntry("normalize.invalid_decimal", "数值字段非法", "normalize", "检查数值格式与精度转换"),
    IngestionCodebookEntry("normalize.empty_not_allowed", "非空字段为空", "normalize", "检查空字符串/空白值处理"),
    IngestionCodebookEntry("normalize.row_transform_failed", "行转换失败", "normalize", "检查 row_transform 逻辑"),
    IngestionCodebookEntry("normalize.payload_invalid", "行内容不符合约束", "normalize", "检查字段类型与结构"),
    IngestionCodebookEntry("write.filtered_by_business_rule", "被业务规则过滤", "writer", "检查策略过滤条件"),
    IngestionCodebookEntry("write.duplicate_conflict_key_in_batch", "同批次冲突键去重", "writer", "检查批次主键冲突"),
    IngestionCodebookEntry("write.target_constraint_filtered", "目标约束导致未写入", "writer", "检查目标表唯一约束/校验规则"),
    IngestionCodebookEntry("reason.unknown", "未归类原因", "normalize", "查看样例明细并补充 reason 映射"),
)


def build_ingestion_codebook_payload() -> dict[str, object]:
    return {
        "version": INGESTION_CODEBOOK_VERSION,
        "updated_at": INGESTION_CODEBOOK_UPDATED_AT,
        "error_codes": [entry.to_dict() for entry in INGESTION_ERROR_CODEBOOK],
        "reason_codes": [entry.to_dict() for entry in INGESTION_REASON_CODEBOOK],
    }
