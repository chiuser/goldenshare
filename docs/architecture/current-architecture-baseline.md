# 当前架构基线（2026-04-06）

本文件是当前唯一有效的工程结构与运行入口说明。

## 1. 子系统与目录

```text
src/
  foundation/   # 数据基座：model/dao/sync/transform/clients/config
  operations/   # 运行时引擎：dispatcher/scheduler/worker 与执行服务
  ops/          # 运维域：ops API、query、schema、ops models
  biz/          # 业务域：quote/market API、query、schema
  platform/     # 平台层：web app、auth、依赖、异常、platform models
  scripts/      # 工程脚本（init-db、create-user、回填脚本）
  shared/       # 共享契约与工具
```

已移除旧目录：`src/web`、`src/services`、`src/dao`、`src/clients`、`src/config`、`src/models`。

## 2. 服务入口

- CLI：`goldenshare = src.cli:app`
- Web：`goldenshare-web = src.platform.web.run:main`
- systemd 示例：`scripts/goldenshare-web.service` 使用 `python -m src.platform.web.run`

## 3. 关键约束

- 不允许新增旧命名空间引用（`src.web.*`、`src.services.*`、`src.dao.*`、`src.clients.*`、`src.config.*`、`src.models.*`）。
- 所有新代码必须落在五个子系统之一：`foundation/operations/ops/biz/platform`。
- 文档中如存在旧路径描述，视为历史材料，不能作为实施依据。

## 4. 验证基线

- 测试：`pytest -q`
- 编译：`python3 -m compileall -q src`

通过以上两项后，视为代码层完成。
