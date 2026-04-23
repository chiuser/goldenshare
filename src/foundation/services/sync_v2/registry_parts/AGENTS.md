# AGENTS.md — `sync_v2/registry_parts/` 规则

## 适用范围

本文件适用于 `src/foundation/services/sync_v2/registry_parts/`。

---

## 1. 目录定位

该目录承接 V2 contract 的分域注册与组装。  
目标：防止 registry 回退成单一超大文件。

---

## 2. 分域规则（强约束）

合同按业务域分文件维护（现行）：

1. `contracts/market_equity.py`
2. `contracts/market_fund.py`
3. `contracts/index_series.py`
4. `contracts/board_hotspot.py`
5. `contracts/moneyflow.py`
6. `contracts/reference_master.py`
7. `contracts/low_frequency.py`

禁止把新增数据集临时塞进错误域文件。

---

## 3. 编码约束

1. 合同新增/迁移优先遵守：
   - `/Users/congming/github/goldenshare/docs/architecture/sync-v2-registry-development-guide-v1.md`
2. builder 约束必须满足，禁止绕过统一构造路径。
3. `assemble.py` 只做组装，不承接业务语义。
4. `contracts.py` 不得重新膨胀为单体 registry 巨文件。

---

## 4. 禁止事项

1. 禁止跨域文件互相复制大段合同。
2. 禁止在 registry 层实现请求策略细节（那是 dataset_strategies 的职责）。
3. 禁止直接依赖 legacy 路径或 V1 注册中心。

---

## 5. 最小门禁

1. `pytest -q tests/architecture/test_sync_v2_registry_guardrails.py`
2. `pytest -q tests/test_sync_v2_registry_routing.py tests/test_sync_registry.py`
3. `goldenshare sync-v2-lint-contracts`

