# 一页技术说明

## 模块结构

```text
run_context.py
    ↓
context_module.service.ContextModule
    ├─ PowerContextClient: import/search/save/resume
    └─ MiniMax OpenAI-compatible HTTP: code modification request
```

工程资料、检索结果和任务状态共用一个明确的 PowerContext Scope：`goalflow-213`。资料以 `SOURCE_ID` 和 `SOURCE_KIND` 前缀保存，查询结果保留来源标识，便于评审定位到规格、代码和测试。

## 上下文选择

1. `import` 读取 fixtures 中的规格、代码和测试索引，通过 PowerContext `remember_memory` 写入数据库。
2. `context` 使用任务描述调用 `search_memory`，只把真实命中的条目组装为 MiniMax 输入。
3. `save-state` 保存完成项、待办项和时间戳。
4. `resume` 重启模块后检索 `goalflow-213-task-state`，恢复后续上下文处理。

## 三项技术分工

| 技术 | 本作业中的实际职责 |
|---|---|
| MiniMax | 根据检索到的 Issue、规格、源码和测试上下文完成 GoalFlow #213 的代码修改，并产出对应提交和测试记录 |
| OceanBase/seekdb | 作为 PowerContext Server 的持久化后端，存储并检索工程规格、代码索引、测试索引和任务状态 |
| PowerContext | 提供 Scope、记忆写入、全文/语义检索和跨重启状态复用入口 |

## 边界

默认不返回源码正文以外的秘密，不记录 API Key，不提交模型私有思维链。PowerContext 的查询结果和 MiniMax 输出只保存可复核的摘要、来源、diff 和测试事实。
