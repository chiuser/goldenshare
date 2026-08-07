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


INGESTION_CODEBOOK_VERSION: Final[str] = "2026-08-07.v1"
INGESTION_CODEBOOK_UPDATED_AT: Final[str] = "2026-08-07T00:00:00Z"

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
    IngestionCodebookEntry("invalid_anchor_date", "锚点日期不符合规则", "validator", "按数据集日期规则选择自然周五、自然月末或其他要求日期"),
    IngestionCodebookEntry("units_exceeded", "执行单元数量超出限制", "planner", "缩小时间窗口或调整 unit 上限"),
    IngestionCodebookEntry("fanout_missing", "分片参数缺失且无默认值", "planner", "补齐 fanout 参数或配置默认值"),
    IngestionCodebookEntry("trade_date_anchor_required", "缺少交易日锚点", "planner", "补齐 trade_date 或 start/end 区间"),
    IngestionCodebookEntry("upstream_data_not_ready", "上游依赖数据未就绪", "planner", "先维护依赖数据集后再重试"),
    IngestionCodebookEntry("universe_empty", "规划范围为空", "planner", "检查股票池/板块池或上游基础数据"),
    IngestionCodebookEntry("unknown_universe_policy", "未知的规划范围策略", "planner", "检查 planning.universe_policy 配置"),
    IngestionCodebookEntry("request_builder_not_found", "请求参数构造器不存在", "planner", "检查 source.request_builder_key 与注册函数"),
    IngestionCodebookEntry("scoped_repair_policy_invalid", "定点补录策略非法", "planner", "检查筛选字段的 scoped_repair_policy 定义"),
    IngestionCodebookEntry("scoped_repair_code_invalid", "定点补录证券代码非法", "planner", "使用一个 6 位数字.(SH|SZ|BJ) 格式的证券代码"),
    IngestionCodebookEntry("scoped_repair_point_required", "定点补录仅支持单个日期", "planner", "改为按单个交易日补录"),
    IngestionCodebookEntry("scoped_repair_bucket_missing", "定点补录日期桶尚未建立", "planner", "先完成该交易日的全市场维护，再补录单只证券"),
    IngestionCodebookEntry("source_adapter_not_found", "数据源适配器不存在", "source", "检查 source_key 与适配器映射"),
    IngestionCodebookEntry("source_timeout", "上游请求超时", "source", "稍后重试或降低并发"),
    IngestionCodebookEntry("source_http_error", "上游 HTTP 异常", "source", "检查状态码和请求参数"),
    IngestionCodebookEntry("source_rate_limited", "上游限流", "source", "降频或延后重试"),
    IngestionCodebookEntry("source_server_error", "上游服务异常", "source", "稍后重试"),
    IngestionCodebookEntry("source_auth_error", "上游鉴权失败", "source", "检查凭据配置"),
    IngestionCodebookEntry("payload_invalid", "上游 payload 不合法", "normalize", "检查字段结构与解析逻辑"),
    IngestionCodebookEntry("all_rows_rejected", "本批次全部行被拒绝", "normalize", "查看 reason 分布并修正数据或规则"),
    IngestionCodebookEntry("normalize.row_transform_failed", "行转换配置或执行失败", "normalize", "检查 row_transform_name 与转换函数"),
    IngestionCodebookEntry("normalize.unit_date_expected_missing", "执行单元缺少日期锚点", "normalize", "检查执行计划的 trade_date"),
    IngestionCodebookEntry("normalize.unit_date_mismatch", "源数据日期与执行单元不一致", "normalize", "检查请求参数与源端返回日期"),
    IngestionCodebookEntry("normalize.source_multiplicity_policy_invalid", "源端重复记录策略非法", "normalize", "检查 Definition 的 source_multiplicity_policy"),
    IngestionCodebookEntry("normalize.source_content_hash_invalid", "源端完整字段内容无法确定性哈希", "normalize", "检查显式 source fields 是否齐全且类型受支持"),
    IngestionCodebookEntry(
        "normalize.required_distinct_values_missing",
        "完整批次缺少必要分类取值",
        "normalize",
        "检查源端完整性和分页范围，禁止用部分结果替换完整快照",
    ),
    IngestionCodebookEntry(
        "normalize.batch_unique_key_duplicate",
        "完整批次的唯一实体键出现完全重复源行",
        "normalize",
        "检查源端分页重叠和实体身份规则，禁止静默去重",
    ),
    IngestionCodebookEntry(
        "normalize.batch_unique_key_conflicting",
        "完整批次的唯一实体键对应不同源内容",
        "normalize",
        "核验源端冲突记录和实体身份规则，禁止任意选择一行",
    ),
    IngestionCodebookEntry("normalize.duplicate_conflict_key_inconsistent", "同一主键出现不一致数据", "normalize", "检查分页结果与源端一致性"),
    IngestionCodebookEntry("dao_not_found", "写入 DAO 路由缺失", "writer", "检查 storage.write_path 与 DAOFactory 注册"),
    IngestionCodebookEntry("write.snapshot_rows_rejected", "完整观察快照存在拒绝行", "writer", "先解决拒绝原因，不能用部分结果替换当前快照"),
    IngestionCodebookEntry("write.snapshot_empty", "完整观察快照为空", "writer", "检查源端返回与字段请求，不能清空当前快照"),
    IngestionCodebookEntry("write.source_entity_key_missing", "观察快照实体键缺失", "writer", "检查数据集行转换的 source_entity_key"),
    IngestionCodebookEntry("write.source_field_missing", "显式请求字段缺失", "writer", "检查 source_fields 与源端返回字段"),
    IngestionCodebookEntry("write.snapshot_content_hash_invalid", "观察快照内容哈希失败", "writer", "检查 source field 类型与哈希序列化"),
    IngestionCodebookEntry("write.snapshot_duplicate_record", "完整观察快照存在重复源记录", "writer", "检查源端分页重叠或身份规则，不能静默去重"),
    IngestionCodebookEntry("write.snapshot_storage_invalid", "观察快照存储契约无效", "writer", "检查 current/observation ORM 与完整 source field 列"),
    IngestionCodebookEntry("write.snapshot_persistence_incomplete", "观察快照持久化行数不一致", "writer", "检查 DAO 写入结果；事务将回滚"),
    IngestionCodebookEntry("write.fact_rows_rejected", "按范围观察事实存在拒绝行", "writer", "先解决拒绝原因，不能用部分结果替换当前范围"),
    IngestionCodebookEntry("write.immutable_rows_rejected", "不可变事实存在拒绝行", "writer", "先解决拒绝原因，不能写入部分日期范围"),
    IngestionCodebookEntry("write.immutable_scope_invalid", "不可变事实日期范围非法", "writer", "核对执行单元和源行公告日期"),
    IngestionCodebookEntry("write.immutable_storage_invalid", "不可变事实存储契约无效", "writer", "检查显式列 ORM 与只插入 DAO 协议"),
    IngestionCodebookEntry("write.immutable_content_hash_invalid", "不可变事实内容哈希失败", "writer", "检查 source field 类型与哈希序列化"),
    IngestionCodebookEntry("write.immutable_identity_invalid", "不可变事实身份依据缺失", "writer", "检查 identity transform 与 identity_basis"),
    IngestionCodebookEntry("write.immutable_identity_conflict", "同批不可变事实身份冲突", "writer", "检查身份字段是否足以唯一表示源事件"),
    IngestionCodebookEntry("write.immutable_scope_regression", "不可变事实范围回退", "writer", "核对源端本次结果是否缺行或为空"),
    IngestionCodebookEntry("write.immutable_fact_conflict", "不可变事实与已有内容冲突", "writer", "人工核对源端是否发生修订或身份规则是否错误"),
    IngestionCodebookEntry("write.immutable_persistence_incomplete", "不可变事实写入核对失败", "writer", "回滚后检查目标表约束和事务状态"),
    IngestionCodebookEntry("write.fact_scope_invalid", "按范围观察事实的日期范围非法", "writer", "检查执行单元日期与源行日期是否一致"),
    IngestionCodebookEntry("write.fact_duplicate_record", "按范围观察事实存在重复实体", "writer", "检查分页重叠或实体身份规则，禁止静默选取"),
    IngestionCodebookEntry("write.fact_content_hash_invalid", "按范围观察事实内容哈希失败", "writer", "检查 source field 类型与哈希序列化"),
    IngestionCodebookEntry("write.fact_storage_invalid", "按范围观察事实存储契约无效", "writer", "检查 current/observation ORM、scope 与完整 source field 列"),
    IngestionCodebookEntry("write.fact_persistence_incomplete", "按范围观察事实持久化行数不一致", "writer", "检查 DAO 写入结果；事务将回滚"),
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
    IngestionCodebookEntry("normalize.numeric_precision_overflow:div_cash", "现金分红精度超出存储上限", "normalize", "核验源值；禁止舍入后写入"),
    IngestionCodebookEntry("normalize.numeric_precision_overflow:base_unit", "分红基数精度超出存储上限", "normalize", "核验源值；禁止舍入后写入"),
    IngestionCodebookEntry("normalize.numeric_precision_overflow:ear_distr", "可分配收益精度超出存储上限", "normalize", "核验源值；禁止舍入后写入"),
    IngestionCodebookEntry("normalize.numeric_precision_overflow:ear_amount", "收益分配金额精度超出存储上限", "normalize", "核验源值；禁止舍入后写入"),
    IngestionCodebookEntry("normalize.empty_not_allowed", "非空字段为空", "normalize", "检查空字符串/空白值处理"),
    IngestionCodebookEntry("normalize.row_transform_failed", "行转换失败", "normalize", "检查 row_transform 逻辑"),
    IngestionCodebookEntry("normalize.payload_invalid", "行内容不符合约束", "normalize", "检查字段类型与结构"),
    IngestionCodebookEntry("normalize.duplicate_conflict_key_in_batch", "同批次完全相同行去重", "normalize", "检查分页结果是否重叠"),
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
