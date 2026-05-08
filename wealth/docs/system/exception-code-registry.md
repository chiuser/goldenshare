# wealth 异常码注册表（统一管理基线）

## 1. 目标

`wealth` 工程内所有模块异常码必须集中管理，禁止分散在各页面文档、代码注释或临时方案中。

本文件是异常码唯一注册表，后续新增模块都必须在这里登记。

---

## 2. 管理范围

1. 市场总览相关接口返回的模块级异常码。
2. debug 模式下返回的 `exceptions` 列表中的 `code` 字段。
3. 前端排障日志与后端观测日志中的结构化异常码。

不在本文件登记的异常码，不允许进入代码和契约。

---

## 3. 命名规范

格式：

```text
<MODULE_PREFIX>_<SCENARIO>
```

示例：

1. `LB_SOURCE_EMPTY`
2. `LB_SOURCE_DELAYED`
3. `LB_QUERY_FAILED`

其中：

1. `LB` 表示 leaderboard 模块。
2. 其他模块后续新增专属前缀（如 `SECTOR_`、`LIMIT_`），但本期不落地。

---

## 4. 注册流程（强制）

新增异常码前必须完成：

1. 在本文件新增条目（含语义、触发条件、前端处理）。
2. 在对应页面级需求文档引用本文件条目，不得重复定义。
3. 再进入代码实现。

若异常语义变化，必须更新注册表并记录“兼容策略/废弃策略”。

---

## 5. 字段模板

每条异常码必须包含以下信息：

| 字段 | 说明 |
|---|---|
| `code` | 异常码唯一标识 |
| `module` | 所属模块（leaderboards/sectorOverview/...） |
| `severity` | `info/warn/error` |
| `userVisible` | 是否直接展示给用户（通常 `false`） |
| `debugOnly` | 是否只在 debug 模式返回 |
| `meaning` | 语义定义 |
| `trigger` | 触发条件 |
| `frontendAction` | 前端处理策略 |
| `owner` | 责任域（app/biz/ops） |
| `phase` | 生效阶段（Phase-1/Phase-2...） |
| `status` | `active/deprecated` |

---

## 6. 首期（Phase-1）已登记：仅榜单模块

> 本期只落地榜单异常码。其他模块后续分期纳入，不在本期范围内。

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `LB_SOURCE_EMPTY` | `leaderboards` | warn | false | true | 榜单源数据为空 | 目标日期无可用行 | 榜单空态 + debug 显示原因 | biz-api | Phase-1 | active |
| `LB_SOURCE_DELAYED` | `leaderboards` | warn | false | true | 榜单源数据日期落后 | `observedTradeDate < expectedTradeDate` | 模块标记 delayed；页面可能 PARTIAL | biz-api | Phase-1 | active |
| `LB_JOIN_METRIC_MISSING` | `leaderboards` | warn | false | true | 指标补列缺失 | daily_basic 等补列 join 失败 | 允许降级展示，缺列用 `--` | biz-api | Phase-1 | active |
| `LB_SUBJECT_NAME_MISSING` | `leaderboards` | info | false | true | 主体名称缺失 | 名称映射不到 | 前端仅显示代码 | biz-api | Phase-1 | active |
| `LB_QUERY_FAILED` | `leaderboards` | error | false | true | 榜单查询失败 | SQL/服务异常 | 模块 error，保留其它模块渲染 | biz-api | Phase-1 | active |

---

## 7. 变更规则

1. 已上线的 `code` 不允许重用为新语义。
2. 废弃码必须保留历史记录，`status=deprecated`，并补替代码。
3. 任何页面文档的异常码段落必须引用本文件，不再各写一套。
