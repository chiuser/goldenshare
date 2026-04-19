# AGENTS.md — `src/app/models` 账户模型规则

## 适用范围

本文件适用于 `src/app/models/` 及其子目录。

---

## 目录定位

`src/app/models` 保存应用壳账户/认证相关 ORM 模型主实现。

---

## 硬约束

1. 不在此目录承载业务规则逻辑。
2. 未经明确任务，不改表名、字段、关系、约束。
3. 任何模型结构变更必须走独立迁移评审，不顺手修改。
4. 保持 metadata 注册与 Alembic 行为稳定。

---

## 改动后说明

每次改动需说明：

1. 是否触及模型结构（通常应为否）
2. 是否影响 metadata / Alembic
3. 是否可能影响 auth/admin API 行为
