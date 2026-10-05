# 周月线 T 前缀代码与身份映射审计

2026-10-05，Asia/Shanghai。管理员要求只解释和审计现状；不补周线、不修改代码、身份映射、正式 Lake 或调度。退市历史保留口径仅限 Raw 周/月线，未决定未来 Silver 周/月线规则。

## 身份表

本文指 DG 既有资产 silver_stock_identity_map，物理文件 `/Volumes/datasource/data_lake/silver/basic/stock_identity_map/part-000.parquet`，不是 Prod 数据库表，也不是周/月线 Silver。由股票生命周期自映射及已登记映射 seed 生成。当前 T600018.SH 和 600018.SH 各自自映射；没有 T600018.SH -> 600018.SH 关系。

## 实查数据

Prod 基础信息中的 T 前缀代码为 T00018.SH、T600018.SH、TS0018.SH，均 D，名称均上港集箱(退)，上市2000-07-19，退市2006-10-20。DG Raw stock_basic 及 lifecycle 中只查到 T600018.SH 这一个 T 前缀记录。600018.SH 两端均为上港集团、L、2006-10-26上市。Tushare MCP 默认字段、文档字段、关键字段三类请求确认 T600018.SH；另查询600018.SH确认独立源记录与生命周期。不能简单去掉T并合并两条身份，也不能由此把所有退市股票都等同于T前缀；DG基础信息339条D记录，仅1条T前缀。

两张 Prod 原始行情表所有 T 前缀记录查询均返回0组；DG五个周/月Raw数据集向量化扫描亦全部为0条T前缀。600018.SH在Prod两源分别有week847行、month201行；DG两主源分别week847行、month200行。月线差1是批准排除20200229重复版本后的结果，并非代码改写。DG周线两主源共1714文件、月线402文件，备用weekly803文件；每数据集文件上限1200、行预算600万，DuckDB内存512MiB、2线程；每数据集汇总查询测得0.056–0.236秒。没有逐分区完整性重算。

## 当前实现

Prod部署版本110254230fcb8f0ff43f145564364c3f40b7d720。直接读取部署中的request_builders、row_transforms、writer，与本机相应路径对照：周线/月线分别请求stk_weekly_monthly或stk_week_month_adj；参数代码只strip/upper；行转换只补change_amount；Raw和core写入投影仅处理日期，不移除T前缀。本次核验的是当前正式实现与现存数据，不证明从前每个版本或外部脚本从未修改过代码。

DG bootstrap保留源ts_code和源行情值；当前代码契约却限制六位数字加SH/SZ/BJ，T前缀在库存/请求或Raw校验处阻断，不会静默改写。周线全表身份检查没有这个六位正则；月线有，因此不属于本月引用对象的T600018.SH仍能阻断新的月线更新意图。该历史对象2006年结束，现有Prod周期行情从2010开始；本次阻断不能解释为缺失月线。

## 身份映射的具体意义和边界

现有已确认例子430017.BJ -> 920017.BJ用于跨源/跨时间换码后的覆盖对账，避免日线与周期行情代码不同被误报为缺失。更新完成检查读取映射后按latest_ts_code比较日线期望与源行情覆盖，不写回源行情ts_code。T600018.SH仍映射自身，不能拿600018.SH替代它。身份未确认会阻断当前更新完成检查。

此前建议只涉及放宽月线对全表身份的额外格式检查，尚未批准实施；Raw允许T前缀是另一个入口合同问题。当前两端周/月Raw实际没有T记录，因此不应由身份表存在T就擅自扩大到周线历史补齐、重建身份或推定Silver清洗/归并策略。

## 执行与证据

使用prod-db-readonly-export、lake-dataset-onboarding、dagster-expert和tushare-contract-validation；CodeGraph explore覆盖请求builder、行情row_transform、身份生成、月线完成检查。Prod仅通过psql-remote.sh，REPEATABLE READ READ ONLY、30秒statement_timeout；先读pg_class估算和pg_indexes，再EXPLAIN确认行情T范围使用主键Index Only Scan。白名单raw_tushare.stock_basic/stk_period_bar/stk_period_bar_adj，仅身份字段、freq、trade_date及计数，T组输出上限101；无行情明细或凭证输出。部署文件经SSH只读核验；首次git因所有者检查失败，改用仓库部署用户读取版本，没有改Git配置。

证据：[Prod查询](stock_t_code_prod_audit_20261005.txt)、[DG物理查询](stock_t_code_dg_audit_20261005.json)、[Tushare身份探测](stock_t_code_source_probe_20261005.json)。只新增这4份报告，不改原LLD、代码、数据库、正式文件、asset/event/sensor或分层依赖；未运行开发测试，因为没有开发改动。
