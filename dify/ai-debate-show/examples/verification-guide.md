# 《再说一遍？AI 记仇辩论夜》完整验收剧本

本文件是评审的**操作手册**：照着做就能得到可复核的验收结论。

- 场景 A：没有 PowerContext 时的降级行为（单机可跑，不需要任何外部服务）
- 场景 B：有真实 PowerContext 时的两会话"翻旧账"（需要目标环境）

> **验证状态**：本机已实际完成 Dify 1.17.1 的导入、发布、无记忆降级三回合，以及同一可信
> Scope 的两会话翻旧账。运行记录见 [`../evidence/dify-e2e.md`](../evidence/dify-e2e.md)；下列步骤可在目标环境重复验收。

---

## 场景 A：无 PowerContext 降级

### 初始条件

```text
未设置 POWERCONTEXT_BASE_URL。
```

Arena 会因此进入无记忆降级模式：游戏照常可玩，只是没有跨会话翻旧账。

### 步骤

#### A1. 启动 Arena

```powershell
cd <仓库根目录>
$env:PYTHONPATH = "dify/ai-debate-show"
python -m arena_service.server
```

或者用启动脚本（会另外写一份带时间戳的日志）：

```powershell
.\dify\ai-debate-show\scripts\start-arena.bat
```

保持这个窗口开着，另开一个窗口做下面的请求。

#### A2. 健康检查

```powershell
$base = "http://127.0.0.1:8088"
Invoke-RestMethod -Uri "$base/health" -Method Get | ConvertTo-Json -Compress
```

#### A3. 创建一局游戏

```powershell
$create = @{
    game_id        = "verify-a-001"
    scope_id       = "verify-scope-a"
    player_nickname = "阿强"
    topic_id       = "pearl-voting-rights"
    initial_stance = "反对"
    opponent_id    = "logic-monster"
} | ConvertTo-Json

$game = Invoke-RestMethod -Uri "$base/games" -Method Post -ContentType "application/json" -Body $create
$game | ConvertTo-Json -Depth 5
```

#### A4. 连续推进三回合

```powershell
$rounds = @(
    @{ player_action = "double_down"; player_message = "珍珠没有手，所以不能投票。" },
    @{ player_action = "double_down"; player_message = "而且投票要用笔写，珍珠连笔都握不住。" },
    @{ player_action = "free_input";   player_message = "行吧，那珍珠当安检员，投票权算工龄福利。" }
)

$results = foreach ($round in $rounds) {
    $body = $round | ConvertTo-Json
    $result = Invoke-RestMethod -Uri "$base/games/$($game.game_id)/rounds" -Method Post -ContentType "application/json" -Body $body
    [pscustomobject]@{
        round_number    = $result.round_number
        selected_card   = $result.selected_card_id
        card_reused     = $result.card_reused
        game_finished   = $result.game_finished
        current_stance  = $result.state.current_stance
        opponent_says   = $result.opponent_message
        follow_up       = $result.follow_up_question
    }
}

$results | Format-List
```

#### A5. 调用记忆写入端点（预期失败）

```powershell
$memory = @{
    player_message = "行吧，那珍珠当安检员，投票权算工龄福利。"
    memory_kind    = "stance"
    memory_text    = "阿强坚持珍珠没有手所以不能投票，理由是投票要手写。"
    reason         = "属于与本局对局直接相关的立场与理由。"
} | ConvertTo-Json

try {
    $response = Invoke-WebRequest -Uri "$base/games/$($game.game_id)/memory" -Method Post `
        -ContentType "application/json" -Body $memory -UseBasicParsing
    "HTTP $([int]$response.StatusCode)`n$($response.Content)"
}
catch {
    $status = 0
    if ($_.Exception.PSObject.Properties["Response"] -and $_.Exception.Response) {
        $status = [int]$_.Exception.Response.StatusCode
    }
    $text = $_.ErrorDetails.Message
    if (-not $text) {
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $text = $reader.ReadToEnd()
        }
        catch {
            $text = ""
        }
    }
    "HTTP $status`n$text"
}
```

### 预期结果

| 检查点 | 预期 |
| --- | --- |
| A2 `/health` | HTTP 200，响应含 `"status":"ok"`、`"service":"ai-debate-show"`、`"memory_configured":false` |
| A3 创建游戏 | HTTP 201，返回 `game_id`、`topic_title`、`current_stance`、`available_actions` |
| A3 记忆状态 | `memory_status="degraded"` |
| A3 历史上下文 | `memory_context` 为 `null` |
| A4 回合推进 | 三次都 HTTP 200；`round_number` 依次为 1、2、3 |
| A4 立场 | 三次 `double_down` / `free_input` 都不翻转立场，`current_stance` 始终是 `反对` |
| A4 卡片 | `selected_card_id` 形如 `pearl-voting-rights-against-logic-01` |
| A4 结束标志 | 第 3 回合 `game_finished=true` |
| A5 写记忆 | HTTP 503，错误码 `memory_unavailable` |

A5 的响应体应当形如：

```json
{
  "error": {
    "code": "memory_unavailable",
    "message": "未配置 PowerContext，记忆写入不可用"
  }
}
```

**这属于正常降级，不是游戏失败。** 三个回合都打完了，结算照常给出，只是这一局没有存进长期档案。

---

## 场景 B：真实 PowerContext 的两会话"翻旧账"

### 初始条件

```text
1. 真实 PowerContext 已运行，且已有一个可信的 scope_id；
2. Arena 已设置 POWERCONTEXT_BASE_URL（必要时设置 POWERCONTEXT_BEARER_TOKEN）；
3. Arena 已启动，且 /health 返回 "memory_configured":true；
4. Dify Chatflow 已导入，并已把三个 LLM 节点绑定到可用模型。
```

> **其中 1–3 已经在真实环境跑过一遍**：仓库自带的
> `scripts/verify-powercontext-e2e.py` 对着真实 Arena + 真实 PowerContext
> 完成了「会话一写入 → 会话二召回」，全部断言通过、退出码 `0`。
> 真实的请求与响应记录见 [`../evidence/powercontext-e2e.md`](../evidence/powercontext-e2e.md)。
> 下面 B1–B5 是**在目标环境复现同一流程**的步骤；本机已实际验证包括 Dify 与模型在内的全部断言。
>
> 只想复现「写入 + 召回」这一段、不碰 Dify 时，直接跑脚本即可：
>
> ```powershell
> $env:ARENA_BASE_URL        = "http://127.0.0.1:8088"
> $env:POWERCONTEXT_BASE_URL = "http://127.0.0.1:8000"
> python dify/ai-debate-show/scripts/verify-powercontext-e2e.py --scope-id <真实 scope_id>
> ```
>
> 脚本的 `game_id` 是固定的，而 Arena 的会话只存在内存里，重复运行前请先重启 Arena。

### 会话一

固定样例：

```text
昵称：阿强
scope_id：同一可信 Scope（会话一与会话二必须完全一致）
辩题：pearl-voting-rights
初始立场：反对
对手：logic-monster
动作：连续三次 double_down 或 free_input
代表性表达：珍珠没有手，所以不能投票。
```

#### B1. 在 Dify 里开一个新会话

开场表单填写：

| 字段 | 值 |
| --- | --- |
| 对局台地址 | `http://127.0.0.1:8088` |
| 档案编号 | 你的可信 `scope_id` |
| 玩家昵称 | `阿强` |
| 辩题编号 | `pearl-voting-rights` |
| 初始立场 | `反对` |
| 对手 | `logic-monster` |
| 本场默认节目动作 | `free_input` |

#### B2. 打完三回合

聊天框依次输入：

```text
[double_down] 珍珠没有手，所以不能投票。
[double_down] 而且投票要手写，珍珠连笔都握不住。
[free_input] 行吧，那珍珠当安检员，投票权算工龄福利。
```

#### B3. 确认结算产出了记忆候选

第三回合后，结算里应当出现荒谬指数、当前人设、代表性名言，以及一条 `memory_candidate`，
类型是 `stance` 或 `quote`。

#### B4. 确认记忆写入成功

Arena 的写回端点返回 HTTP 200：

```json
{"status":"recorded"}
```

记录这一行响应，它就是"会话一的旧账真的存进去了"的直接证据。

### 会话二

固定样例：

```text
使用同一 scope_id；
使用同一昵称阿强；
仍选择 pearl-voting-rights；
初始立场改为支持；
至少完成第一回合。
```

#### B5. 新开一个 Dify 会话（不是继续刚才那个）

同一个 Scope，不同的会话。填写同样的昵称 `阿强`、同样的 `scope_id`，
但初始立场改成 `支持`，然后至少打完第一回合：

```text
[free_input] 其实我改主意了，珍珠当然能投票，远程投票又不靠手。
```

### 验收断言

| # | 断言 | 怎么看 |
| --- | --- | --- |
| 1 | 会话一开局**没有历史时不得伪造旧账** | 会话一的 `memory_status` 若是 `degraded`（第一次玩必然如此），主持人口播里不能出现"上次""上回""你说过"这类话 |
| 2 | 会话一第三回合后写入成功 | B4 的响应为 HTTP 200 且内容是 `{"status":"recorded"}` |
| 3 | 会话二开局返回 `memory_status="ready"` | 会话二创建游戏（`POST /games`）的响应里 `memory_status` 是 `ready`，且 `memory_context` 不是 `null` |
| 4 | 会话二的 `memory_context` 与会话一相关 | `memory_context` 里出现会话一的立场或代表论点（例如"珍珠没有手"、或"反对"），而不是无关内容 |
| 5 | Dify 回应形成"翻旧账" | 会话二主持人的口播引用或改写了会话一的历史（节目语气），并把它和本局的新立场放在一起说 |
| 6 | Dify **不得逐字照抄**反击卡 | 对手台词与 `content-draft/rebuttal_cards.draft.json` 里的卡片原文不是逐字相同；逻辑内核一致、措辞不同 |
| 7 | 会话二改口后，结算记忆记录**本局最终立场** | 会话二第三回合后的 `memory_candidate.text` 写的是本局结束时的立场（`支持`），反转过程另记为 `reversal` |
| 8 | 两会话的 `game_id` 不同、但 `scope_id` 相同 | 两个会话的 `game_id` 由各自的会话标识派生，必然不同；填进表单的 `scope_id` 必须一模一样 |

### 建议保存的证据

| 证据 | 用来证明 |
| --- | --- |
| Dify 首轮输入截图 | 证明 Scope ID 是显式填入的可信输入，不是猜出来的 |
| 会话一的结算截图 | 证明荒谬指数、人设、名言与记忆候选都产出了 |
| Arena `recorded` 响应 | 证明会话一的记忆真的写进了 PowerContext |
| 会话二出现历史相关回应的截图 | 证明"翻旧账"是运行时行为，不是文案写死的 |
| PowerContext 侧的请求/响应或节点执行记录 | 证明召回与写入都真的走到了 PowerContext |

其中「Arena `recorded` 响应」「PowerContext 侧的请求/响应」两项已有一份可核对的
真实记录：[`../evidence/powercontext-e2e.md`](../evidence/powercontext-e2e.md)
（其中包含 Scope 创建响应、会话一的 `recorded` 响应、会话二的
`memory_status="ready"` 与召回内容、以及服务端侧回读到的那条记忆条目）。

### 排障顺序（会话二没有历史时）

按顺序排查，不要跳步：

1. **先确认会话一记忆写入是否 returned**——B4 的 `POST /games/{game_id}/memory` 是否返回了 `{"status":"recorded"}`；没写入成功，后面都不用查。
2. **确认两会话 `scope_id` 完全一致**——逐字符比对，包括大小写和前后空格。
3. **确认 Arena 没有进入 degraded**——查 `GET /health` 的 `memory_configured` 是否为 `true`，再查会话二 `POST /games` 的 `memory_status` 是否为 `ready`。
4. **确认 PowerContext 服务地址与认证**——`POWERCONTEXT_BASE_URL` 是否指向真实服务；`POWERCONTEXT_BEARER_TOKEN` 是否正确；`POWERCONTEXT_TIMEOUT_SECONDS` 是否合理；再看 Arena 日志里的具体报错。
5. **不得通过伪造 `memory_context` 制造"成功"**——宁可判定为未通过，也不要手动改写上下文或伪造回放。历史缺失时宁可不翻旧账，也不虚构玩家说过的话。

---

## 两套场景的对照速查

| | 场景 A | 场景 B |
| --- | --- | --- |
| PowerContext | 未配置 | 已配置且可达 |
| `/health` 的 `memory_configured` | `false` | `true` |
| 开局 `memory_status` | `degraded` | `ready` |
| 开局 `memory_context` | `null` | 与上一局相关的历史文本 |
| 三回合 | 正常打完 | 正常打完 |
| 写回档案 | 503 `memory_unavailable` | 200 `{"status":"recorded"}` |
| 跨会话翻旧账 | 没有 | 有 |
| 是否需要外部服务 | 否 | 是 |
