# MiniMax × OceanBase：GoalFlow Issue #213

本目录是竞赛提交材料和可运行演示。演示模块从 PowerContext 的公开 Client 入口导入、检索并复用任务上下文；PowerContext Server 的数据库后端配置为 OceanBase 或嵌入式 seekdb 时，工程资料和任务状态实际落在对应数据库中。

## 依赖与配置

在仓库根目录执行：

```powershell
uv sync --extra builtin --extra client --extra server
```

启动 PowerContext Server 时使用 OceanBase 或 seekdb 配置。不要把凭据写入文件：

```powershell
$env:MINIMAX_DB_KIND = "oceanbase"
$env:MINIMAX_OCEANBASE_URL = "mysql+aoceanbase://<user>:<password>@<host>:<port>/<database>"
python minimax/start_server.py
```

Linux/macOS 也可以使用嵌入式 seekdb：

```bash
MINIMAX_DB_KIND=seekdb MINIMAX_SEEKDB_PATH=.powercontext/seekdb python minimax/start_server.py
```

没有数据库服务时，可仅用 SQLite 做本地 smoke test；它不替代比赛要求的 OceanBase/seekdb 验收。

```text
POWERCONTEXT_BASE_URL=http://127.0.0.1:8000
MINIMAX_CONTEXT_SCOPE=goalflow-213
MINIMAX_CHAT_URL=https://api.minimax.io/v1/chat/completions
MINIMAX_MODEL=MiniMax-M3
MINIMAX_API_KEY=<placeholder>
```

`MINIMAX_CHAT_URL`、模型名和 API Key 都可替换为比赛账号实际提供的 OpenAI-compatible 入口。当前实现不会打印 API Key，也不会把它写入 PowerContext。

## 调用入口

在 `minimax/` 目录执行：

```powershell
python run_context.py init
python run_context.py import fixtures
python run_context.py context "Issue 213 context manifest owner budget truncation tests"
python run_context.py save-state --completed=import,context --pending=minimax,verify
python run_context.py resume
```

`context` 的输出来自 PowerContext 的数据库检索结果，不是固定答案；修改 `fixtures/issue-213.md` 后重新运行 `import`，查询结果会使用更新内容。`resume` 会在模块重启后从 PowerContext 读取已保存的状态。

MiniMax 实际调用由 `ContextModule.call_minimax()` 完成；调用前必须把 `context` 命令输出作为上下文传入。模型返回、脱敏提示和代码差异记录在 `records/`，不得提交私有思维链或凭据。

## GoalFlow 验证结果

目标项目：GoalFlow Issue #213。MiniMax 分支基于 `origin/main @ c37bf63`：

- 基线提交：`4166918303ebbc312a2f76395857adef107e451a`
- 实现提交：`c81dee05b6e705bea1ef4efe91d4ad0aefc8170d`
- 目标测试：11 failed → 11 passed
- 后端：1881 passed
- 前端：156 passed
- `scripts/check.sh`：退出码 0，无跳过
- `scripts/test.sh`：退出码 0，无跳过

完整证据见 `records/`；GoalFlow 原始修改位于其独立工作树和分支，不污染本仓库既有未提交修改。
