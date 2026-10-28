# PowerContext 状态复用记录

```text
scope_id: goalflow-213
state_kind: goalflow-213-task-state
write: python run_context.py save-state --completed=import,context --pending=minimax,verify
restart: 退出模块进程后重新执行 python run_context.py resume
expected: 返回 task_id、completed、pending、saved_at
```

状态不是本地临时 JSON；`save-state` 调用 PowerContext Client 的 `remember_memory`，`resume` 调用 `search_memory` 读取，因此重启模块后仍可恢复。
