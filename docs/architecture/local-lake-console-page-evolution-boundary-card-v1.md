# Local Lake Console 页面演进边界卡 v1

- 版本：v1
- 状态：待评审
- 更新时间：2026-05-11
- 适用范围：`lake_console/frontend`
- 关联文档：
  - [Local Lake 管理台升级路线图 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-management-roadmap-v1.md)
  - [Local Lake Recovery / Write Safety 页面交互设计 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-recovery-write-safety-page-design-v1.md)

---

## 1. 目标

本边界卡只回答两件事：

1. 当前已经存在的页面，哪些保留，哪些改造，哪些弱化为抽屉 / 侧栏详情。
2. 第一期新页面只做什么，不做什么。

本卡不展开具体视觉细节，不展开后端 API，不进入编码实现。

---

## 2. 当前真实页面清单

当前 `lake_console/frontend` 实际存在 4 个页面：

1. `datasets`
2. `datasetDetail`
3. `commands`
4. `risks`

代码入口见：

- [main.tsx](/Users/congming/github/goldenshare/lake_console/frontend/src/main.tsx)
- [AppShell.tsx](/Users/congming/github/goldenshare/lake_console/frontend/src/components/AppShell.tsx)

---

## 3. 页面演进总原则

1. 不推倒现有页面体系重做。
2. 不保留“有页面就继续堆功能”的粗放扩展方式。
3. 总览页保留，总览负责发现问题，不负责承载全部详情。
4. 详情优先进入抽屉 / 侧栏，而不是继续扩大独立详情页。
5. 第一期新增页面只盯 `Recovery / Write Safety`，不同时展开 `Health / Storage / Activity`。
6. 页面文案遵守统一口径：
   - 高密度
   - 低噪声
   - 少废话文案
   - 表格优先
   - 抽屉 / 侧栏承载详情

---

## 4. 现有页面保留 / 改造清单

### 4.1 `datasets`

结论：**保留并升级**

职责：

1. 继续作为默认首页。
2. 继续负责 Lake 数据集总览。
3. 强化筛选、排序、状态密度、容量密度、层级密度。
4. 弱化解释性文案。
5. 详情不再主要依赖跳独立页，后续优先从右侧抽屉展开。

不做：

1. 不在总览页承载恢复记录全量列表。
2. 不在总览页承载 schema 对比细节。
3. 不在总览页堆长说明。

### 4.2 `datasetDetail`

结论：**保留能力，弱化独立页形态**

职责调整：

1. 保留数据集详情能力本身。
2. 详情能力后续优先转为：
   - 总览页右侧抽屉
   - Health 页面抽屉
   - Recovery 页面关联对象侧栏
3. 独立详情页短期可继续存在，作为过渡入口。

后续方向：

1. 新交互优先从抽屉 / 侧栏进入详情。
2. 独立详情页不再继续扩容为大而全页面。

### 4.3 `commands`

结论：**保留并升级**

职责：

1. 保留命令浏览入口。
2. 从“静态示例页”升级到更接近 `Command Center`。
3. 后续支持按对象上下文带出命令模板。

不做：

1. 第一期不接真实执行按钮。
2. 第一期不做远程调度。

### 4.4 `risks`

结论：**保留并收窄**

职责：

1. 保留基础风险总览页。
2. 更偏向：
   - Lake 根目录风险
   - 基础文件风险
   - 通用异常汇总

后续分流：

1. 恢复相关风险 -> `Recovery`
2. 完整性相关风险 -> `Health`
3. 空间 / 保留相关风险 -> `Storage`

不做：

1. 不继续把所有治理问题都塞进 `risks`。

---

## 5. 新页面一期边界

第一期新增页面只做 1 个：

1. `Recovery / Write Safety`

暂不进入实现的新页面：

1. `Health`
2. `Storage`
3. `Activity`

这些页面仍保留在路线图里，但不进入本批编码。

---

## 6. 第一期导航形态

本批建议导航调整为：

```text
Datasets
Recovery
Commands
Risks
```

说明：

1. `datasetDetail` 不作为一级导航保留。
2. `datasetDetail` 继续存在为内部详情能力。
3. `Recovery` 成为第一批新增一级入口。
4. `Health / Storage / Activity` 先不进一级导航。

---

## 7. 第一期实现边界

允许：

1. 调整 `AppShell` 导航结构。
2. 调整 `datasets` 页面布局与详情打开方式。
3. 新增 `Recovery` 页面。
4. 新增 `Recovery` 相关抽屉 / 侧栏详情组件。
5. 为 `commands` 和 `risks` 做最小必要的导航适配。

不允许：

1. 同时重做全部页面视觉系统。
2. 顺手实现 `Health / Storage / Activity`。
3. 顺手重构所有共享组件。
4. 趁机改后端语义边界。
5. 在前端自行拼装恢复事实、备份事实或数据健康事实。

---

## 8. 验收口径

本卡对应的一期页面边界完成后，应满足：

1. 管理台首页仍可稳定查看数据集总览。
2. `Recovery` 成为一级入口。
3. 详情交互开始从“独立页为主”向“抽屉 / 侧栏为主”迁移。
4. 本批范围内没有把 `Health / Storage / Activity` 偷偷混进实现。
5. 页面数量和导航结构与本边界卡一致。
