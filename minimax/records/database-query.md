# 数据库实际参与记录

上下文模块不自建第二套资料库，而是调用 PowerContext Client：

- `import` → `remember_memory`，把规格、代码索引和测试索引写入当前 Scope；
- `context` → `search_memory`，查询结果直接作为 MiniMax 上下文；
- `save-state` → `remember_memory`，保存任务状态；
- `resume` → `search_memory`，重启后读取任务状态。

PowerContext Server 的 `database` 配置支持：

- OceanBase MySQL tenant：`OceanBaseConfig`；
- Linux/macOS 嵌入式 seekdb：`SeekDBConfig`。

本机 Windows smoke test 使用 PowerContext 的 SQLite profile 只验证 Client/Server 调用链；评审环境应按运行说明切换到 OceanBase 或 seekdb，并保留 `context` 命令的真实检索输出作为数据库参与证据。SQLite smoke test 不冒充 OceanBase/seekdb 验收。
