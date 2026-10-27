# 《再说一遍？AI 记仇辩论夜》Dify 导入说明

本文件说明如何把 `ai-debate-show-chatflow.yml` 导入 Dify，把它和本地 Arena 服务连起来，
让评审在 Dify 的 Web App 里直接体验三回合辩论与「翻旧账」。

---

## 1. 适用的 Dify 版本与 DSL 依据

### 1.1 版本

| 项目 | 值 |
|---|---|
| DSL `version` 字段 | `"0.6.0"` |
| 应用模式 | `app.mode: advanced-chat`（Chatflow） |
| 官方当前 DSL 版本 | `"0.7.0"`（`api/constants/dsl_version.py` 的 `CURRENT_APP_DSL_VERSION`） |
| 已实测环境 | Dify 1.17.1（Chatflow 已导入、已发布、降级三回合已跑通） |
| 建议目标环境 | Dify 1.17.x；其他支持 Chatflow 的版本请按本说明复核 |

为什么声明 `0.6.0` 而不是 `0.7.0`：这份 DSL 只用到 `0.6.0` 基线就有的节点能力
（Chatflow、HTTP Request、If/Else、Variable Assigner、LLM、Answer、Code），
**不涉及 `0.7.0` 才有的 Agent App package / Agent v2 结构**。按官方
`api/services/dsl_version.py` 的 `check_version_compatibility`：

- 目标 Dify 的 `CURRENT_APP_DSL_VERSION` 等于 `0.6.0` → `COMPLETED`（无提示导入）；
- 等于 `0.7.0` → `COMPLETED_WITH_WARNINGS`（提示一次 DSL 版本较旧，仍会正常导入）；
- 低于 `0.6.0` → `PENDING`，Dify 会弹一次「DSL 版本较新，是否继续导入」的确认框，确认后正常导入。

**已在本机 Dify 1.17.1 完成真实导入、发布、三回合降级路径，以及同一可信 Scope 的两会话翻旧账验证。**验证中发现
1.17 的 JSON HTTP body 要求每个节点只保留一个完整 JSON 模板，已写入本 DSL；第三回合在
不存在的演示 Scope 下按预期落到「结算（档案未入库）」分支；可信 Scope 的写入、召回和
主持人翻旧账也已跑通。完整运行记录见 [`../evidence/dify-e2e.md`](../evidence/dify-e2e.md)。

### 1.2 实际查阅的官方来源

以下链接是编写这份 DSL 时实际拉取过的源文件或官方页面（均取 `langgenius/dify` 的 `main` 分支）：

- 导入流程与 DSL 顶层结构：`https://raw.githubusercontent.com/langgenius/dify/main/api/services/app_dsl_service.py`
  （确认 `version` / `kind` / `app` / `dependencies` / `workflow.environment_variables` / `workflow.conversation_variables` / `workflow.graph` 的读取方式）
- 当前 DSL 版本常量：`https://raw.githubusercontent.com/langgenius/dify/main/api/constants/dsl_version.py`
- 版本兼容判定：`https://raw.githubusercontent.com/langgenius/dify/main/api/services/dsl_version.py`
- 变量命名空间前缀（`sys` / `env` / `conversation`）：`https://raw.githubusercontent.com/langgenius/dify/main/api/core/workflow/variable_prefixes.py`
- 会话变量的字段要求（必须有 `name` / `value_type` / `value`）：`https://raw.githubusercontent.com/langgenius/dify/main/api/factories/variable_factory.py`
- 通用节点字段（`title` / `desc` / `error_strategy` / `retry_config` / `default_value`）、`InputVar`、`ModelConfig`、`PromptItem`：`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/types.ts`
- HTTP Request 节点字段与 `Timeout` 类型：`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/nodes/http/types.ts`
- HTTP 节点超时字段名是 `connect` / `read` / `write`（`max_*_timeout` 只是前端上限）：`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/nodes/http/components/timeout/index.tsx`
- 后端 `HttpRequestNodeTimeout(connect=..., read=..., write=...)` 的官方 issue 佐证：`https://github.com/langgenius/dify/issues/23284`
- HTTP 节点超时上限的环境变量（`HTTP_REQUEST_MAX_CONNECT_TIMEOUT` 等）：`https://github.com/langgenius/dify/discussions/22083`
- LLM 节点字段（`model` / `prompt_template` / `context` / `vision`）：`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/nodes/llm/types.ts`
- If/Else 节点字段（`cases` / `case_id` / `conditions` / `comparison_operator`）：`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/nodes/if-else/types.ts`
- Variable Assigner v2 字段（`items` / `variable_selector` / `input_type` / `operation`）：`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/nodes/assigner/types.ts`
- Answer 节点字段（`answer` / `variables`）：`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/nodes/answer/types.ts`
- 错误处理与重试字段：`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/nodes/_base/components/error-handle/types.ts`、`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/nodes/_base/components/retry/types.ts`
- 会话变量取值类型：`https://raw.githubusercontent.com/langgenius/dify/main/web/app/components/workflow/panel/chat-variable-panel/type.ts`

节点文档页（用于人工复核，页面由前端渲染，抓取后正文不完整，仅作引用）：
`https://docs.dify.ai/zh/use-dify/nodes/http-request`、`https://docs.dify.ai/zh/use-dify/nodes/llm`、
`https://docs.dify.ai/zh/use-dify/nodes/if-else`、`https://docs.dify.ai/zh/use-dify/nodes/answer`、
`https://docs.dify.ai/zh/use-dify/nodes/variable-assigner`

### 1.3 这份 DSL 用到的节点

| 节点 | 数量 | 作用 |
|---|---:|---|
| Start | 1 | 首轮收集参赛信息 |
| Code | 5 | 解析动作前缀、派生 game_id、拆 JSON、取结算候选 |
| If/Else | 2 | 本场状态判断、是否第三回合 |
| Variable Assigner | 2 | 把对局编号 / 回合号 / 档案状态写进会话变量 |
| HTTP Request | 3 | 开局、推进回合、写回档案 |
| LLM | 3 | 回合导演、综艺结算、降级播报 |
| Answer | 5 | 回合回应、节目结算、档案未入库、已收工、现场信号中断 |

没有使用任何自定义插件，也没有在 DSL 里写入任何真实地址、令牌或模型 Key。

---

## 2. 导入步骤

1. 启动 Arena 服务（见第 4 节）。
2. 打开 Dify 控制台 → 「工作室」→ 「导入 DSL」。
3. 上传 `dify/ai-debate-show/dify/ai-debate-show-chatflow.yml`。
4. 导入后在应用「编排」页检查一遍画布：应当看到 21 个节点、22 条连线，首尾连通，没有断边。
5. 按第 3 节把三个 LLM 节点（`主持人与对手回合导演`、`第三回合综艺结算`、`降级播报`）
   的模型改成你工作区里已经配好凭据的供应商与模型。
6. 点右上角「发布」，再进「预览」或「运行」体验。

> 导入时如果 Dify 提示「缺少插件」，说明你的工作区没有装 DSL 里占位用的模型供应商插件。
> 装上，或者直接在第 3 节把模型换成本地已有的供应商即可。

---

## 3. 需要在 Dify 里重新绑定的模型

DSL 里三个 LLM 节点都用同一个占位模型：

```yaml
model:
  provider: langgenius/deepseek/deepseek
  name: deepseek-chat
  mode: chat
```

**导入后必须逐个改成你工作区实际可用的模型**，因为 DSL 里不写任何模型凭据，
换供应商不会自动生效。三个节点都要改：

| 节点 | 建议温度 | 说明 |
|---|---:|---|
| `主持人与对手回合导演` | 0.8 | 需要综艺感，保留格式三段 |
| `第三回合综艺结算` | 0.7 | 需要稳定输出 JSON |
| `降级播报` | 0.3 | 只需要一句话，低温度更稳 |

模型必须支持中文与「只输出 JSON」；`降级播报` 用小模型即可。

---

## 4. 启动 Arena API

```powershell
$env:PYTHONPATH = "dify/ai-debate-show"
python -m arena_service.server
```

默认监听 `127.0.0.1:8088`。健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8088/health
```

返回形如 `{"status":"ok","service":"ai-debate-show","memory_configured":false}`。

如果 Dify 跑在 Docker 里，而 Arena 跑在宿主机上，DSL 的「对局台地址」要填
`http://host.docker.internal:8088`，不能填 `127.0.0.1`——容器里的 `127.0.0.1` 是容器自己。

---

## 5. 首轮输入字段怎么填

首轮会在 Dify 的开场表单里收这些字段，填完在聊天框发出第一段发言：

| 字段 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| 对局台地址 | 是 | `http://127.0.0.1:8088` | Arena 根地址，**不要带结尾斜杠** |
| 档案编号 | 是 | `demo-player` | 由可信调用方提供，用来关联历史档案；同一个编号就是同一个人的旧账。它就是 PowerContext 的 Scope ID，准备方式见下面的「Scope 准备」 |
| 玩家昵称 | 是 | `阿强` | 只在节目内使用 |
| 辩题编号 | 是 | `pearl-voting-rights` | 见下表 |
| 初始立场 | 是 | `反对` | `支持` / `反对` |
| 对手 | 是 | `logic-monster` | `logic-monster`（逻辑怪）/ `contrarian`（抬杠王） |
| 本场默认节目动作 | 否 | `free_input` | `double_down` / `switch_explain` / `wild_card` / `free_input` |
| 对局编号兜底种子 | 否 | 空 | 只有当你的 Dify 拿不到会话标识时才需要填 |

可用辩题编号（8 个，来自 `content-draft/topics.json`）：

`pearl-voting-rights`、`pet-office-workers`、`refrigerator-mayor`、`cloud-union-representative`、
`traffic-light-driving-license`、`cat-night-shift-magistrate`、`umbrella-tax-exemption`、`moon-property-registration`

### 每回合怎么指定节目动作

Chatflow 的开场表单只在首轮出现，所以动作支持两种写法：

1. **聊天框前缀（推荐，可逐回合切换）**：发言前面加一个方括号动作名，例如
   `[switch_explain] 其实我换个说法，珍珠当然能投票。`
   解析规则在 `code_action` 节点里：前缀合法就用前缀，不合法就当没有前缀。
2. **首轮表单里的「本场默认节目动作」**：没有前缀时用它。

动作含义：`double_down` 坚持原立场硬刚；`switch_explain` 换个说法（**会翻转立场**）；
`wild_card` 放个狠招；`free_input` 自由发挥（不改立场）。

### 对局编号（game_id）从哪来

`game_id` **不由用户输入**。`code_session` 节点用 Dify 的会话标识 `sys.conversation_id` 派生：

```
game_id = "debate-" + 会话标识
```

同一个 Dify 会话 = 同一局游戏；换一个新会话 = 换一局。

如果你的 Dify 版本拿不到 `sys.conversation_id`（`code_session` 报错或恒为空），
在首轮表单里填「对局编号兜底种子」，它会顶替会话标识；或者直接改 `code_session` 节点的
`main` 函数，把 `conversation_id` 换成一个固定前缀。

---

## Scope 准备

「档案编号」就是 PowerContext 的 **Scope ID**。它决定节目能翻到谁的旧账，
必须由可信调用方提供，不能由系统猜出来。

### 如果评审环境已经预分配了 Scope

直接用它的 `scope_id`，跳过下面的创建步骤。这是**最常见的情况**：
预分配的 Scope 往往还带好了权限与归属，比临时创建一个更稳。

### 如果需要自己创建一个

依据 `openapi/powercontext.yaml` 的真实定义：

```text
POST /v1/scopes
```

请求体对应 `CreateScopeRequest`（`additionalProperties: false`，只接受下列字段）：

| 字段 | 必填 | 约束 | 说明 |
|---|---|---|---|
| `title` | 是 | 1–256 字符，不能全空白 | 这个 Scope 的标题 |
| `summary` | 是 | 1–2000 字符，不能全空白 | 这个 Scope 的用途说明 |
| `idempotency_key` | 是 | 1–256 字符，不能全空白 | 幂等键；重复提交同一个键不会创建出两个 Scope |
| `parent_scope_id` | 否 | 1–256 字符，可为 `null` | 父 Scope，没有就留空 |
| `context_references` | 否 | 字符串数组，默认 `[]` | 关联的上下文引用 |
| `external_references` | 否 | 数组，默认 `[]` | 关联的外部引用 |

**成功状态是 HTTP 201**，响应体是 Scope 描述对象（`ScopeDescriptor`），
里面的 `scope_id` 就是要填进 Dify 开场表单「档案编号」的那个值。

**创建 Scope 需要对应的服务端权限**：该端点在契约里标注了 `server.admin` 级别的访问要求，
普通调用方的令牌通常会被拒绝（401/403）。没有权限时，请让环境管理员预分配一个 Scope，
而不是绕过权限。

示例一（curl，令牌用环境变量占位）：

```bash
curl -sS -X POST "$POWERCONTEXT_BASE_URL/v1/scopes" \
  -H "Authorization: Bearer $POWERCONTEXT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "AI 记仇辩论夜 演示玩家",
    "summary": "《再说一遍？》演示用玩家档案，用于验证跨会话翻旧账。",
    "idempotency_key": "ai-debate-show-demo-scope-001"
  }'
```

示例二（PowerShell `Invoke-RestMethod`，令牌用环境变量占位）：

```powershell
$headers = @{ Authorization = "Bearer $env:POWERCONTEXT_TOKEN" }

$body = @{
    title           = "AI 记仇辩论夜 演示玩家"
    summary         = "《再说一遍？》演示用玩家档案，用于验证跨会话翻旧账。"
    idempotency_key = "ai-debate-show-demo-scope-001"
} | ConvertTo-Json

Invoke-RestMethod -Uri "$env:POWERCONTEXT_BASE_URL/v1/scopes" `
    -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

### 三条硬规矩

1. **不得猜测 Scope**。Dify、Arena 都不得根据昵称、模型输出、目录名或分支名拼一个 Scope ID 出来。
   PowerContext 的契约里也写明：普通的召回、检索或保存都不会创建 Scope，
   Scope 身份不能从目录或分支推断出来。
2. **Scope ID 是 Dify 开场表单里的可信输入**，由评审或运营方填入；
   `Arena` 只负责透传，不会替它做推导。
3. **Scope 创建不属于玩家对局流程**。它是一次性的环境准备动作，
   玩家点「开始辩论」时既不创建 Scope，也不该看到任何 Scope 相关的东西。

---

## 6. 运行三回合的完整样例

下面是一次完整的三回合样例。假设：

- 对局台地址：`http://127.0.0.1:8088`
- 档案编号：`demo-player`
- 玩家昵称：阿强
- 辩题编号：`pearl-voting-rights`（珍珠是否应拥有投票权）
- 初始立场：反对
- 对手：logic-monster（逻辑怪）

**第 1 轮**

聊天框输入：

```
[double_down] 珍珠连手都没有，投票要用手写才有效，所以它不该有投票权。
```

节目组返回：主持人报题并接住这句，逻辑怪用「远程投票靠的是身份确认，不是手」反击，
追问「那么没有手的人或物，是否不该拥有投票权？」。这一轮立场不变，仍是 `反对`。

**第 2 轮**

聊天框输入：

```
[switch_explain] 我换个说法：珍珠可以雇人代投，代投的人有手，所以投票权其实在代投人手里。
```

节目组返回：主持人点出玩家换了个说法、立场已经调转；逻辑怪顺着新的说法反击并抛出新追问。
这一轮立场翻转成 `支持`。

**第 3 轮**

聊天框输入：

```
[free_input] 行吧，那珍珠当安检员，投票权就算工龄福利。
```

节目组返回：第三回合结束后进入结算，节目组给出荒谬指数、当前人设、代表性名言和本局记忆候选，
并把记忆候选写回长期档案。**本局到此结束，不会再开第四回合**；
再发一条消息会收到「本场已收工」的提示。

**降级演示（可选）**：把 Arena 启动时**不设置** `POWERCONTEXT_BASE_URL`，
再开一个新会话玩一轮，主持人会走「本场没有旧账」的说法，而不是报出任何技术细节。

---

## 7. 配置 `POWERCONTEXT_BASE_URL` 与可选令牌

记忆能力在 **Arena 服务端**配置，不在 Dify 里配。DSL 里的 HTTP 节点**不带任何认证头**
（`authorization: {type: no-auth}`），Arena 到 PowerContext 的认证由服务端环境变量完成。

```powershell
$env:POWERCONTEXT_BASE_URL = "http://127.0.0.1:8000"
$env:POWERCONTEXT_BEARER_TOKEN = "<从密钥存储读取>"
$env:POWERCONTEXT_TIMEOUT_SECONDS = "10"
$env:PYTHONPATH = "dify/ai-debate-show"
python -m arena_service.server
```

- `POWERCONTEXT_BASE_URL`：不设置就没有「翻旧账」能力。
- `POWERCONTEXT_BEARER_TOKEN`：可选；不设置就不发 `Authorization` 头。
- `POWERCONTEXT_TIMEOUT_SECONDS`：可选，默认 10。

改完环境变量要重启 Arena 服务，配置才会生效。

---

## 8. Scope 准备

「档案编号」就是 PowerContext 的 `scope_id`，它决定这一局能翻到**谁**的旧账。
Dify 与 Arena 都**不会**根据昵称、模型输出、目录名或分支名去猜 Scope：`scope_id`
必须由可信调用方显式提供，并作为开场表单里的一项输入传进来。

### 8.1 环境里已经预分配了 Scope

直接用现成的 `scope_id`，不需要创建。把它填进开场表单的「档案编号」，Arena 会原样
透传给 PowerContext。想确认这个值可用：以它开一局，看 `POST /games` 的响应里
`memory_status` 是否为 `ready`。如果配置正确但该 Scope 还没有任何记忆，返回
`degraded` 也是正常的——空档案就代表这一局没有旧账可翻。

### 8.2 需要新建一个 Scope

创建 Scope 是**管理员操作**：`openapi/powercontext.yaml` 里 `POST /v1/scopes` 声明的是
`server.admin` 级别的访问要求，调用者必须具备对应的服务端权限，否则会被拒绝。
**这个调用不属于普通玩家对局流程**：它是一个一次性的环境准备动作，做完一次即可反复使用
同一个 `scope_id`。

请求体三个字段都必填：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | Scope 标题，1~256 字符，不能全空白 |
| `summary` | string | Scope 摘要，1~2000 字符，说明这个 Scope 装的是什么 |
| `idempotency_key` | string | 幂等键，1~256 字符；重试时用同一个值，避免重复创建 |

成功状态是 **HTTP 201**，响应体是 Scope 描述对象，其中 `scope_id` 就是要填进 Dify
开场表单的值：

```json
{
  "scope_id": "<服务端返回的 scope 标识>",
  "title": "《再说一遍？》演示档案",
  "summary": "AI 记仇辩论夜的跨会话游戏记忆",
  "context_references": [],
  "external_references": [],
  "version": 1
}
```

`curl` 示例（占位值，**不要**把真实令牌写进任何文件或截图）：

```bash
export POWERCONTEXT_BASE_URL="http://127.0.0.1:8000"
export POWERCONTEXT_TOKEN="<从密钥存储读取>"

curl -sS -X POST "${POWERCONTEXT_BASE_URL}/v1/scopes" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${POWERCONTEXT_TOKEN}" \
  -d '{
    "title": "《再说一遍？》演示档案",
    "summary": "AI 记仇辩论夜的跨会话游戏记忆",
    "idempotency_key": "ai-debate-show-demo-scope-001"
  }'
```

PowerShell `Invoke-RestMethod` 示例（令牌从环境变量读取，不写在脚本里）：

```powershell
$base = "http://127.0.0.1:8000"
$token = "<从密钥存储读取>"      # 真实使用时不落盘、不截图
$headers = @{ Authorization = "Bearer $token" }

$body = @{
    title           = "《再说一遍？》演示档案"
    summary         = "AI 记仇辩论夜的跨会话游戏记忆"
    idempotency_key = "ai-debate-show-demo-scope-001"
} | ConvertTo-Json

$scope = Invoke-RestMethod -Method Post -Uri "$base/v1/scopes" `
    -ContentType "application/json" -Headers $headers -Body $body

$scope.scope_id
```

### 8.3 拿到 scope_id 之后

1. 把它填进 Dify 开场表单的「档案编号」；同一个 Scope 就是同一个人的档案。
2. 会话一与会话二必须使用**完全一致**的 `scope_id`，跨会话记忆才成立。
3. Arena 不创建、不猜测、不持久化 Scope：`scope_id` 永远来自这个可信输入。

记忆没有召回时的排查顺序见
[`../examples/verification-guide.md`](../examples/verification-guide.md) 的「排障顺序」一节。

## 9. 没有 PowerContext 时的降级行为

Arena 服务在没有配置 `POWERCONTEXT_BASE_URL` 时：

- 开局照常成功，返回 `memory_status="degraded"`、`memory_context=null`；
- 对局照常进行，三个回合都能打完；
- 主持人只说「本场没有旧账」这类节目内说法（由 `降级播报` 节点产出），**不暴露任何技术细节**；
- 写回档案的端点返回 503，结算照常显示，只是最后补一句「本局档案暂未入库」。

已经配置了 PowerContext 但它此刻不可用时，表现完全一样：开局降级成功，不中断对局。

---

## 10. 记忆写入失败时的玩家可见表现

第三回合结算完成后，节目组会把记忆候选写回长期档案。写回失败时：

1. **结算照常显示**——荒谬指数、人设、代表性名言都不受影响；
2. 结尾补一条固定播报：**「本局档案暂未入库，这一局的战绩只留在节目现场。」**
   （`answer_memory_failed` 节点里的固定文案，逐字不变）；
3. **不会重跑整局**，不会要求玩家重来一遍。

失败可能来自：Arena 没配 `POWERCONTEXT_BASE_URL`（503）、PowerContext 调用失败（502）、
同类型记忆重复写入（409）。三种情况的玩家可见表现一致。

---

## 11. 已知限制

- **服务会话只在内存里**。Arena 进程重启后所有对局消失，玩家必须重新开始一局；
  PowerContext 里的长期记忆不受影响。同一局请不要中途重启 Arena 服务。
- **同一个 Dify 会话只对应一局**。想再玩一次，请回到开场**新开一个会话**；
  在同一个会话里重跑开场会撞上「对局编号已存在」。
- **一局最多三回合**。第三回合后必定结算，不会出现第四回合。
- **`card_reused=true` 时素材会重复**。对同一辩题、立场和对手的卡池可能只有 2 张；
  连续三回合不改立场时，第 3 回合可能复用。提示词已要求复用时换角度换句式。
- **目标环境仍需复核模型与网络**。本机 Dify 1.17.1 已跑通；换用其他 Dify 版本、模型供应商或容器网络时，必须按第 6 节重跑验证样例。
- **HTTP 节点的异常分支**依赖 Dify 的 `error_strategy: fail-branch`。
  如果你的 Dify 版本不支持 HTTP 节点的异常分支，失败时工作流会直接中断而不是落到
  「现场信号中断」的降级回答，请按目标版本复核。
- **`arena_base_url` 必须是 Arena 服务的根地址**，且不要带结尾斜杠；
  DSL 会在这个地址后面拼 `/games`、`/games/{id}/rounds`、`/games/{id}/memory`。
- **模型不得杜撰历史**。`memory_context` 为空时，主持人和结算都不会声称记得玩家过去的发言。

---

## 12. 凭据与隐私

- 本目录的 DSL、`PROMPTS.md`、本文件里**没有任何真实地址、令牌、口令或模型 Key**。
- DSL 里的模型配置只是供应商与模型名，真正的凭据留在 Dify 工作区的模型供应商设置里。
- Arena 服务端的 `POWERCONTEXT_BEARER_TOKEN` 属于服务端环境变量，不进版本库。
- 「档案编号」（`scope_id`）由可信调用方提供，它决定节目能翻到谁的旧账；
  正式部署时不要让前端用户随意填写。
