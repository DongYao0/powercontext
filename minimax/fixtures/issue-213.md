# GoalFlow Issue #213

提供只读上下文清单查询入口。

要修改：为已持久化的 context manifest 增加只读列表和详情查询入口。

必须保持：owner 隔离、稳定排序、不返回正文、不改变 Context Assembler、检索排序、预算分配和 Agent 注入行为。

验收：目标测试修改前失败，修改后通过；完整后端与前端回归测试通过。
