# platform 拆分与 cleanup 基线（收敛后版本）

## 文档目的

记录 `platform -> app/biz/ops` 拆分后的真实状态，并定义 post-cutover 清理策略。  
本版本仅保留现状与后续策略，不保留历史阶段日志，避免误导。

---

## 拆分结果（已完成）

1. app 壳基础（dependencies/exceptions）已迁至 `src/app/*`
2. auth/admin 链路已迁至 `src/app/auth/*`
3. 账户模型已迁至 `src/app/models/*`
4. app 通用 schema 已迁至 `src/app/schemas/*`
5. API 聚合入口已迁至 `src/app/api/*`
6. web 主入口与支撑模块已迁至 `src/app/web/*`
7. 旧市场快照试点业务线已删除，不再作为业务系统基线
8. 运行静态资源主路径已收敛到 `src/app/web/static`

---

## 当前状态

### 主实现目录

1. `src/app/**`：应用入口与装配主实现
2. `src/biz/**`：业务接口主实现
3. `src/ops/**`：运维治理主实现

### legacy 目录

`src/platform` 当前定位为 legacy 占位目录，不再承接主实现。

---

## 护栏

1. `tests/architecture/test_platform_legacy_guardrails.py`
2. `tests/architecture/test_subsystem_dependency_matrix.py`

护栏目标：

1. 禁止运行代码/测试代码回流导入 `src.platform.*`
2. 禁止 `src/platform` 回长 Python 主实现
3. 固化静态资源路径为 `src/app/web/static`

---

## 清理策略（post-cutover）

### 已执行

1. `platform` 下兼容壳主文件已完成清理
2. 运行链路对 `src.platform.*` 直接导入已清零（受护栏约束）

### 可选下一步（非阻塞）

1. 是否删除 legacy 空包骨架（`src/platform/**/__init__.py`）
2. 是否进一步收缩 `src/platform` 目录到仅保留 `AGENTS.md`

---

## 删除 legacy 骨架风险评估

### 风险等级：低到中

主要风险不在仓库内运行代码，而在**仓库外**可能仍存在的旧导入（例如外部脚本）：

1. 外部脚本仍 `import src.platform...` 会在删除后直接失败
2. 团队成员本地未更新命令/脚本时可能出现短期断链

### 降险前置条件（必须）

1. 全仓引用审计（`src + tests + scripts + docs + README + pyproject + .github`）无旧导入
2. 最小回归通过（architecture + web 关键测试）
3. 文档/AGENTS 已同步到“无 compat 主实现”状态

### 执行建议

若满足前置条件，可执行删除；否则继续保留骨架一轮并记录阻塞点。

---

## 当前建议结论

1. 功能层面已完成拆分目标，可进入长期稳定维护。
2. 后续工作以“低风险清理 + 防回退护栏”为主，不再做大迁移。
