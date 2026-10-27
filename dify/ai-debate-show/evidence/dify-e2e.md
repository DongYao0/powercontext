# Dify × Arena × PowerContext 真实联调记录

本记录只描述实际完成的运行结果；不包含 Scope ID、令牌、账号、模型密钥或服务端返回的完整历史正文。

## 环境

| 组件 | 实际验证版本或形态 |
| --- | --- |
| Dify | 本机 Docker 部署的 1.17.1，Chatflow 已导入并发布 |
| Arena | 本仓库 `arena_service.server`，`memory_configured=true` |
| PowerContext | 本机已运行的 1.2.0 实例 |
| 文案模型 | Dify 工作区已配置的 DeepSeek Flash |

## 实际执行链路

1. 导入并发布 `dify/ai-debate-show-chatflow.yml`。
2. 在 Dify Web App 中，以不存在的演示 Scope 完成三个回合：前两回合均获得主持人、对手与追问；第三回合进入“结算（档案未入库）”，验证无记忆降级不阻断游戏。
3. 使用一个可信 Scope 完成三回合真实会话。Dify 的“写回本局档案”节点返回 HTTP 200，正文为 `{"status":"recorded"}`。
4. 新开一个 Dify 会话，填入同一可信 Scope、同一昵称与相反的初始立场。Dify 的“开一场新对局”和“解析开局结果”节点均返回 `memory_status="ready"`，且解析到非空历史上下文。
5. 第二会话第一回合的主持人明确引用上一局“反对珍珠投票权”的旧立场及“安检员工龄福利”表达，并与本局“支持远程投票”并置；对手随即围绕前后门槛矛盾反击。

## 可复核的关键结果

| 验收点 | 实际结果 |
| --- | --- |
| Dify 导入与发布 | 成功 |
| Dify HTTP 调 Arena | 成功，创建、推进和写回节点均执行 |
| 无记忆降级 | 三回合可完成；第三回合给出“档案未入库”提示 |
| 真实记忆写回 | 成功，Arena 返回 `{"status":"recorded"}` |
| 真实历史召回 | 成功，Dify 节点读到 `memory_status="ready"` 与非空上下文 |
| 跨会话翻旧账 | 成功，主持人将上一局反对立场与本局支持立场并置 |
| 对手不照抄反击卡 | 成功，实际对手台词为重新组织的节目化表达 |

## 本次发现并修复的 Dify 兼容性问题

1. Dify 1.17 的 HTTP Request JSON body 每个节点需要一个完整 JSON 模板；原来按字段拆成多个 body item 会失败。DSL 已改为三个请求各一个 JSON 模板。
2. Variable Assigner 的默认 JSON 必须作为字符串保存；原先 YAML 对象会在运行期被拒绝。DSL 已改为 JSON 字符串。
3. DeepSeek Flash 的 2000 token 上限可能只产生推演文本、没有最终台词。回合与结算节点已提高至 4096，并要求只输出最终文本。
4. 历史上下文已经到达 Dify 还不足以保证节目效果；回合提示词已要求在 `ready` 时主持人改写一条相关旧账，与当前立场并置。

## 复现边界

完整复现步骤见 [`../examples/verification-guide.md`](../examples/verification-guide.md)。
PowerContext 单独的原始读写证据见 [`powercontext-e2e.md`](powercontext-e2e.md)。
