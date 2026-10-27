# 《再说一遍？》Arena 服务调用契约

本文档描述本地 Arena HTTP 服务的对外契约，供 Dify Chatflow 通过 HTTP Request
节点调用。

## 1. 服务职责与边界

Arena 服务负责**确定性的部分**：

- 建立一局游戏、维护三回合状态；
- 在开局时准备历史记忆上下文（从 PowerContext 读取）；
- 决定本回合使用哪一张反击卡，并把卡片原文交给上层；
- 维护立场、已用卡片与结算时机；
- 在结算后把经审核的游戏记忆写入 PowerContext。

Arena 服务**不负责**：

- 不生成任何模型文案。主持人口播与对手的综艺化措辞由 Dify 侧的模型产出；
  服务只提供 `opponent_message`（卡片原文）、`follow_up_question`（卡片追问）
  与回合状态作为素材。
- 不做玩家账号、鉴权与计费。
- 不把玩家文本交给模型；模型在 Dify 侧调用。

一句话：**模型负责怎么说，服务负责算什么。**

## 2. 启动与配置

```powershell
$env:PYTHONPATH = "dify/ai-debate-show"
python -m arena_service.server
```

配置全部来自环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ARENA_HOST` | `127.0.0.1` | 监听地址 |
| `ARENA_PORT` | `8088` | 监听端口 |
| `POWERCONTEXT_BASE_URL` | 无 | PowerContext 根地址，例如 `http://127.0.0.1:8000`；缺失时记忆能力降级 |
| `POWERCONTEXT_BEARER_TOKEN` | 无 | 可选 Bearer 令牌；缺失时不发送 Authorization 头 |
| `POWERCONTEXT_TIMEOUT_SECONDS` | `10` | 可选；必须是大于 0 的有限数值 |

占位示例（**不要**把真实令牌写进任何文档或代码）：

```powershell
$env:ARENA_HOST = "127.0.0.1"
$env:ARENA_PORT = "8088"
$env:POWERCONTEXT_BASE_URL = "http://127.0.0.1:8000"
$env:POWERCONTEXT_BEARER_TOKEN = "<从密钥存储读取>"
$env:POWERCONTEXT_TIMEOUT_SECONDS = "10"
```

### 2.1 会话只存在于内存

Arena 把对局状态保存在进程内存中，**不落盘**。服务重启后所有会话消失，
玩家必须重新开始一局，PowerContext 里的长期记忆不受影响。

### 2.2 PowerContext 故障只降级“翻旧账”

- 未配置 `POWERCONTEXT_BASE_URL`：开局返回 `memory_status="degraded"`、
  `memory_context=null`；对局照常进行；记忆写入端点返回 503。
- 已配置但 PowerContext 调用失败：开局同样降级成功，不中断对局；
  记忆写入失败返回 502，并区分来源证据是否已保存。

## 3. 通用约定

- 所有响应都是 `application/json; charset=utf-8`。
- 所有写操作只接受 `Content-Type: application/json`，请求体必须是 JSON 对象。
- 错误响应格式固定：

```json
{
  "error": {
    "code": "invalid_request",
    "message": "可诊断、但不含令牌的错误说明"
  }
}
```

`error.details` 是可选扩展，目前只出现在 502 场景，用于区分来源证据是否已保存。

| 情况 | HTTP | code |
|---|---:|---|
| 非法 JSON、缺字段、类型或取值不合法 | 400 | `invalid_request` |
| `game_id` 不存在 | 404 | `game_not_found` |
| 重复 `game_id`、游戏已结束、重复写同类记忆 | 409 | `invalid_state` |
| 未配置 PowerContext | 503 | `memory_unavailable` |
| PowerContext 调用失败 | 502 | `powercontext_error` |
| 其他未预期异常 | 500 | `internal_error` |
| 未知接口路径 | 404 | `not_found` |
| 不支持的方法 | 405 | `method_not_allowed` |

服务不会在响应里返回异常堆栈、环境变量取值或 Bearer 令牌。

## 4. 端点

### 4.1 `GET /health`

健康检查，不需要请求体。

成功响应 `200`：

```json
{
  "status": "ok",
  "service": "ai-debate-show",
  "memory_configured": true
}
```

### 4.2 `POST /games`

创建一局游戏并准备历史记忆上下文。

请求体：

```json
{
  "game_id": "game-001",
  "scope_id": "trusted-scope-id",
  "player_nickname": "阿强",
  "topic_id": "pearl-voting-rights",
  "initial_stance": "反对",
  "opponent_id": "logic-monster"
}
```

| 字段 | 说明 |
|---|---|
| `game_id` | 本局标识，全局唯一；重复创建返回 409 |
| `scope_id` | 由可信调用方显式提供；服务不会从昵称或玩家文本推导 Scope |
| `player_nickname` | 节目内昵称 |
| `topic_id` | 辩题 id |
| `initial_stance` | `支持` 或 `反对` |
| `opponent_id` | `logic-monster` 或 `contrarian` |

成功响应 `201`：

```json
{
  "game_id": "game-001",
  "scope_id": "trusted-scope-id",
  "player_nickname": "阿强",
  "topic_id": "pearl-voting-rights",
  "topic_title": "珍珠是否应拥有投票权",
  "opponent_id": "logic-monster",
  "current_stance": "反对",
  "completed_rounds": 0,
  "memory_context": "……召回到的历史上下文……",
  "memory_status": "ready",
  "available_actions": ["double_down", "switch_explain", "wild_card", "free_input"]
}
```

`memory_status` 取值：

| 取值 | 含义 |
|---|---|
| `ready` | 召回到历史上下文，`memory_context` 是可用文本 |
| `degraded` | 没有可用历史（未配置、调用失败、Scope 为空），`memory_context` 为 `null` |

**无论历史是否可用，合法游戏都创建成功。**

### 4.3 `POST /games/{game_id}/rounds`

推进一个回合。路径中的 `game_id` 是 URL 编码后的标识。

请求体：

```json
{
  "player_action": "double_down",
  "player_message": "珍珠没有手，所以不能投票。"
}
```

| 字段 | 说明 |
|---|---|
| `player_action` | `double_down` / `switch_explain` / `wild_card` / `free_input` |
| `player_message` | 玩家本回合实际发言 |

成功响应 `200`：

```json
{
  "round_number": 1,
  "player_action": "double_down",
  "player_message": "珍珠没有手，所以不能投票。",
  "selected_card_id": "pearl-voting-rights-against-logic-01",
  "opponent_message": "远程投票需要的是身份确认，不是手；你的手机也没有手，照样天天投票。",
  "follow_up_question": "那么没有手的人或物，是否不该拥有投票权？",
  "card_reused": false,
  "game_finished": false,
  "state": {
    "game_id": "game-001",
    "player_nickname": "阿强",
    "topic_id": "pearl-voting-rights",
    "opponent_id": "logic-monster",
    "current_stance": "反对",
    "completed_rounds": 1,
    "used_card_ids": ["pearl-voting-rights-against-logic-01"],
    "finished": false
  },
  "available_actions": ["double_down", "switch_explain", "wild_card", "free_input"]
}
```

要点：

- `opponent_message` 与 `follow_up_question` 是**卡片原文**，不是模型生成内容；
  Dify 侧模型应在其基础上做综艺化改写。
- `card_reused=true` 表示本局该立场的卡片已用尽，本次复用了排序第一张。
- `game_finished=true` 表示第三回合结束，Dify 应转入结算与记忆候选生成。

### 4.4 `POST /games/{game_id}/memory`

写入本局结算记忆。只允许已结束的游戏调用，同一种 `memory_kind` 不能重复写入。

请求体：

```json
{
  "player_message": "第三回合玩家实际发言",
  "memory_kind": "stance",
  "memory_text": "阿强在……",
  "reason": "属于与游戏直接相关的立场与理由。"
}
```

| 字段 | 说明 |
|---|---|
| `player_message` | 最后一个回合玩家实际发言 |
| `memory_kind` | `stance` / `quote` / `persona` / `promise` / `reversal` / `catchphrase` |
| `memory_text` | 记忆正文，UTF-8 不超过 8192 字节 |
| `reason` | 写入理由，不超过 512 字符 |

成功响应 `200`：

```json
{"status": "recorded"}
```

失败场景：

- 游戏未结束或同类型记忆已写过 → 409 `invalid_state`；
- 未配置 PowerContext → 503 `memory_unavailable`；
- PowerContext 调用失败 → 502 `powercontext_error`，
  `error.details.source_recorded` 为 `true` 表示来源证据已保存但长期记忆未写成，
  为 `false` 表示连来源证据都没存下来。

## 5. Dify Chatflow 调用顺序

```text
开始节点
  → HTTP POST /games
  → LLM：结合 memory_context、玩家输入、RoundPlan 生成主持人口播
  → HTTP POST /games/{id}/rounds
  → LLM：结合 selected_card 原文生成综艺化回应
  → 第三回合条件判断
  → LLM：输出结算与 memory_candidate
  → HTTP POST /games/{id}/memory
  → 结束
```

分工说明：

| 节点 | 职责 |
|---|---|
| `POST /games` | 建立对局、取回历史上下文；`memory_status=degraded` 时照常继续，只是没有旧账可翻 |
| LLM（主持） | 依据 `memory_context`、玩家输入和当前状态写主持人口播 |
| `POST /games/{id}/rounds` | 推进回合、确定本回合卡片与追问 |
| LLM（对手） | 依据 `opponent_message`（卡片原文）与 `follow_up_question` 做综艺化回应 |
| 条件分支 | `game_finished=false` 回到下一回合；`true` 进入结算 |
| LLM（结算） | 产出荒谬指数、人设变化、本局名言与 `memory_candidate` |
| `POST /games/{id}/memory` | 把审核过的 `memory_candidate` 写进 PowerContext |

模型不要自己编造 `selected_card_id` 或 `opponent_message`，一律以服务返回的原文为准。

## 6. Dify Chatflow 绑定

`dify/ai-debate-show-chatflow.yml` 把上面四个端点串成一段可导入的 Chatflow。
本节说明节点顺序与字段约定，导入与运行步骤见 `dify/DIFY_IMPORT.md`，
提示词原文见 `dify/PROMPTS.md`。

### 6.1 节点顺序

```text
开始
  → 代码：解析动作前缀与玩家原话
  → 代码：用会话标识派生 game_id
  → 分支：是否本场已收工
      ├─ 是：回答（已收工）
      ├─ 首轮：HTTP POST /games
      │        → 代码：解析开局结果
      │        → LLM：降级播报
      │        → 变量赋值：保存 game_id / 档案状态 / 辩题 / 降级播报
      └─ 否：↓
  → HTTP POST /games/{game_id}/rounds
  → 代码：解析回合结果
  → 变量赋值：记录回合号与是否收工
  → LLM：主持人与对手回合导演
  → 分支：是否第三回合
      ├─ 否：回答（继续）
      └─ 是：LLM：第三回合综艺结算
              → 代码：解析结算结果（长度与枚举兜底）
              → HTTP POST /games/{game_id}/memory
                  ├─ 成功：回答（节目结算）
                  └─ 失败：回答（结算照常 + 本局档案暂未入库）
```

### 6.2 game_id 怎么来

`game_id` **不由用户输入**。Chatflow 用 Dify 的会话标识派生：

```text
game_id = "debate-" + sys.conversation_id
```

同一个 Dify 会话对应同一局；换会话就是换一局。目标 Dify 拿不到 `sys.conversation_id` 时，
用开始节点的「对局编号兜底种子」顶上（`game_id` 只能含可打印 ASCII）。

### 6.3 每回合的动作

开始节点的表单只在首轮出现，所以节目动作支持聊天框前缀：

```text
[double_down] / [switch_explain] / [wild_card] / [free_input]
```

前缀合法就取前缀，不合法就当没有前缀、退回开始节点里的默认动作。
`player_message` 是去掉前缀之后的正文。

### 6.4 字段对照

| 服务返回 | Chatflow 侧落点 | 用在哪 |
|---|---|---|
| `topic_title` | 会话变量 `topic_title` | 主持人口播、结算 |
| `memory_status` | 会话变量 `memory_status` | 降级判断（`ready` / `degraded`） |
| `memory_context` | 会话变量 `memory_context` | 翻旧账的素材；为空时不得声称记得玩家 |
| `opponent_message` | 代码节点输出 | 反击要点的逻辑内核（模型要换说法） |
| `follow_up_question` | 代码节点输出 | 追问的原意 |
| `card_reused` | 代码节点输出 | `true` 时必须换角度换句式 |
| `game_finished` | 会话变量 `game_finished` + 分支条件 | 是否转入结算 |
| `state.current_stance` | 代码节点输出 | 主持人播报当前立场 |
| `selected_card_id` | 代码节点输出 | 仅供排错，模型不得复述 |

### 6.5 降级如何落到玩家眼前

| 情况 | 服务返回 | 玩家看到 |
|---|---|---|
| 未配置 PowerContext | `memory_status="degraded"` | 主持人说「本场没有旧账」，不提任何技术细节 |
| PowerContext 调用失败 | 同上，开局不中断 | 同上 |
| 结算时写回失败 | 503 / 502 | 结算照常显示，末尾补一句「本局档案暂未入库」 |
| 对局台没接上 | 连不上 | 「现场信号中断」，提示回到开场重新入席 |

模型不参与降级判定：降级与否由服务返回的字段和 HTTP 状态码决定，模型只负责把
既定事实说成节目语言。
