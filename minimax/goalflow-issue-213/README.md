# GoalFlow Issue #213 交付快照

这些文件是 MiniMax 在 GoalFlow 分支上的实际修改和生成契约快照。完整基线来自 `Doar999/GoalFlow` 的 `origin/main @ c37bf63`；实现分支为 `minimax/issue-213-context-manifest`。

提交顺序：

1. `4166918303ebbc312a2f76395857adef107e451a`：新增目标测试，修改前 11 项失败；
2. `c81dee05b6e705bea1ef4efe91d4ad0aefc8170d`：服务、路由注册和生成契约实现。

在原始 GoalFlow checkout 中复现：

```bash
git fetch origin
git checkout minimax/issue-213-context-manifest
bash scripts/check.sh
bash scripts/test.sh
```

`../records/goalflow-issue-213.patch` 是从 `origin/main...HEAD` 生成的二进制安全 diff；本目录只保留与 Issue #213 直接相关的源码、测试和契约文件，便于评审核对。
