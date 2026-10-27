# 再说一遍？AI 记仇辩论夜

> 每一句嘴硬，都会成为下一期的开场白。

一款单人回合制文字综艺辩论游戏：玩家围绕荒诞辩题连打三个回合，节目组会把你这一局的立场、名言和翻车瞬间记进档案；等你用同一个身份再进一次，主持人会当着所有人的面，把你上次说过的话念给你听。

## 好玩在哪里

- **辩题是真的荒谬**：珍珠该不该有投票权？冰箱要不要竞选 Mayor？加班狗能不能当猫的夜班法官？每一题都值得抬杠。
- **对手会抓你的漏洞**：逻辑怪专抓前后矛盾和概念偷换；抬杠王专挑你上次的旧账下手。
- **改口是有代价的**：你可以嘴硬到底（`double_down`）、改口解释（`switch_explain`）、甩出离谱新论点（`wild_card`），也可以自由发挥（`free_input`）。改口会被主持人当场点名，结算时荒谬指数照算不误。
- **你的黑历史会回来找你**：上一局说过"珍珠没有手所以不能投票"，下一局换了立场，主持人会慢悠悠地把这句原话复述一遍——这是本作品真正的主菜。
- **荒谬指数只评价节目效果**：不评价你的智力、人格和现实身份，只评价这一段有多好笑。

## 玩家如何体验

1. 打开 Dify Web App，在开场表单里填好：昵称、辩题、立场、对手、档案编号（Scope）。
2. 在聊天框发出你的第一段发言；之后每一回合都可以用 `[double_down]`、`[switch_explain]`、`[wild_card]`、`[free_input]` 前缀指定节目动作。
3. 主持人和对手会给出综艺化回应和一句追问；一共三个回合。
4. 第三回合结束立刻结算：荒谬指数、当前人设、本局代表性名言，以及一条会被存进档案的记忆。
5. 换个会话、换个立场再来一局，如果同一个 Scope 里已经有你的历史，你会在开场就被"翻旧账"。

## 系统架构

```text
玩家
  ↓
Dify Chatflow
  ↓ HTTP Request
Arena API
  ├─ 内容目录、反击卡、三回合状态机
  └─ PowerContext
       ├─ 开局历史上下文召回
       └─ 第三回合结算记忆写入
```

## Dify / Arena / PowerContext 分工

| 组件 | 角色 | 具体负责 |
| --- | --- | --- |
| **Dify Chatflow** | 玩家入口 + 流程编排 + 文案层 | 提供 Web App 入口；用 HTTP Request 节点调 Arena；用 LLM 节点写主持人口播、对手回应和结算；把会话变量（game_id、回合号、档案状态）串起来；生成记忆候选 |
| **Arena API** | 确定性规则层 | 维护三回合状态机；按辩题 + 立场 + 对手从内容目录选反击卡；开局调用 PowerContext 准备历史上下文；第三回合后把审核过的记忆写回 PowerContext；对局台只提供受控 HTTP 接口，不生成任何模型文案 |
| **PowerContext** | 跨会话记忆层 | 保存每个 Scope 的长期记忆；开局按 Scope 召回相关历史；结算时写入本局记忆。**"上一局的立场/名言在下一局被召回并影响回应"就是靠它实现的** |

**关于 seekdb**：本作品**不使用 seekdb**。赛题要求"必须实际使用 seekdb 或 PowerContext 至少一种"，PowerContext 已经满足这条指定技术要求；反击卡与辩题以 JSON 形式随仓库分发在 `content-draft/`，不依赖外部向量库。（`PRODUCT.md` 里的技术分工表把 seekdb 列进了素材库职责，那是设计阶段的规划，实际实现没有引入它。）

**没有 PowerContext 也能玩**：不配置 `POWERCONTEXT_BASE_URL` 时，开局返回 `memory_status="degraded"`、`memory_context=null`，三回合照常打完，只是不存在跨会话的"翻旧账"；结算时写回档案会返回 503，节目组照常给出结算并提示"本局档案暂未入库"。

**Arena 会话只在内存**：对局状态不落盘，Arena 进程重启后当前三回合对局需要重新开始；PowerContext 里的长期记忆不受影响。

**关于验证的诚实说明**：静态测试与单元测试之外，已在本机 Dify 1.17.1 完成真实导入、发布、无记忆降级三回合，以及同一可信 Scope 的两会话翻旧账全链路验证。详细记录见 [`evidence/dify-e2e.md`](evidence/dify-e2e.md)。

## 项目目录

```text
dify/ai-debate-show/
├── README.md                       ← 本文件，评审第一入口
├── .env.example                    ← 配置占位参考（复制后自行改）
├── PRODUCT.md                      ← 产品定位与体验目标
├── INTERACTION.md                  ← 交互契约（业务语义冻结）
├── API_CONTRACT.md                 ← Arena HTTP 契约 + Dify Chatflow 绑定
├── arena_service/                  ← 确定性规则层 + HTTP 服务（纯标准库）
│   ├── app.py                      ← 应用层：会话、回合、记忆写入
│   ├── content.py                  ← 内容目录加载与反击卡选择
│   ├── game.py                     ← 三回合状态机
│   ├── game_memory.py              ← 记忆事件与写入策略
│   ├── models.py                   ← 内容数据模型
│   ├── powercontext.py             ← PowerContext 客户端
│   └── server.py                   ← HTTP 服务入口
├── content-draft/                  ← 节目素材（8 辩题 / 3 角色 / 48 张反击卡）
├── contracts/                      ← 请求响应样例
├── dify/
│   ├── ai-debate-show-chatflow.yml ← 可导入的 Dify Chatflow DSL
│   ├── DIFY_IMPORT.md              ← 导入步骤、Scope 准备、模型绑定
│   └── PROMPTS.md                  ← 三份中文提示词（与 DSL 逐字一致）
├── examples/
│   ├── two-session-playthrough.md   ← 两会话剧本
│   └── verification-guide.md        ← 完整验收剧本（无 PowerContext / 有 PowerContext）
├── scripts/
│   ├── start-arena.bat             ← Windows 启动脚本
│   └── start-arena.sh              ← Unix 启动脚本
└── tests/                          ← 单元测试与交付资产完整性测试
```

## 环境要求

| 项目 | 要求 |
| --- | --- |
| Python | 3.11 或更高版本，**只用标准库**（无第三方依赖，不需要 pip install） |
| Dify | 支持 Chatflow（`advanced-chat`）的版本；建议 1.13 ~ 1.16 |
| PowerContext | 可选。没有它游戏照常可玩，只是没有跨会话翻旧账 |
| 操作系统 | Windows 10+ 或任意 POSIX 环境（各有一份启动脚本） |

## 快速启动

### Windows

```powershell
cd <仓库根目录>
.\dify\ai-debate-show\scripts\start-arena.bat
```

### Unix

```bash
cd dify/ai-debate-show
chmod +x scripts/start-arena.sh
./scripts/start-arena.sh
```

脚本会自己定位项目目录（不依赖你当前在哪个目录），检查 Python、检查端口占用、创建 `logs/`
并生成带时间戳的日志文件，然后在前台启动服务。**脚本不会结束任何进程，也不会安装任何依赖。**

手动启动（等价）：

```powershell
$env:PYTHONPATH = "dify/ai-debate-show"
python -m arena_service.server
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8088/health
```

预期返回 `{"status":"ok","service":"ai-debate-show","memory_configured":false}`（未配置 PowerContext 时 `memory_configured` 为 `false`）。

服务日志默认写在 `dify/ai-debate-show/logs/arena-<时间戳>.log`（UTF-8 编码），实时查看：

```powershell
Get-Content -Wait -Encoding UTF8 .\dify\ai-debate-show\logs\arena-*.log
```

`logs/` 是脚本运行时生成的目录，不属于交付内容，提交前可以直接删掉。

## 配置 PowerContext

Arena 的全部配置来自环境变量，仓库里的 `.env.example` 只是复制配置时的参考文件，**Arena 不会自动读取它**。

```powershell
$env:POWERCONTEXT_BASE_URL = "http://127.0.0.1:8000"
$env:POWERCONTEXT_BEARER_TOKEN = "<从密钥存储读取>"
$env:POWERCONTEXT_TIMEOUT_SECONDS = "10"
$env:ARENA_HOST = "127.0.0.1"
$env:ARENA_PORT = "8088"
```

- `POWERCONTEXT_BASE_URL` 不设置 → 无记忆降级模式；
- `POWERCONTEXT_BEARER_TOKEN` 可选，不设置就不发送认证头；
- 令牌只放在服务端环境变量里，**不要写进任何文件**。

另外还需要一个**可信的 Scope ID**：它是"谁的旧账"的唯一依据，必须由可信调用方提供，不能由昵称、模型输出或目录名推导。创建方法见 [`dify/DIFY_IMPORT.md`](dify/DIFY_IMPORT.md) 的「Scope 准备」一节。

## 导入 Dify

1. 启动 Arena（见上一节）。
2. Dify 控制台 →「工作室」→「导入 DSL」→ 上传 `dify/ai-debate-show/dify/ai-debate-show-chatflow.yml`。
3. 把三个 LLM 节点重绑到工作区里可用的模型（DSL 里是占位供应商，不含任何凭据）。
4. 准备一个 Scope，把 `scope_id` 填进开场表单的「档案编号」。
5. 发布并体验。

完整步骤、字段说明、DSL 版本依据和已知限制见 [`dify/DIFY_IMPORT.md`](dify/DIFY_IMPORT.md)。

## 验证样例

- **真实 PowerContext 联调已验证**（本机真实服务、真实写入、真实召回的请求与响应记录）：
  [`evidence/powercontext-e2e.md`](evidence/powercontext-e2e.md)
- **真实 Dify 全链路联调已验证**（导入、发布、三回合、写回与跨会话翻旧账）：
  [`evidence/dify-e2e.md`](evidence/dify-e2e.md)
- **完整验收剧本**（无 PowerContext 降级 / 有 PowerContext 两会话翻旧账，含每一步的命令、预期与证据清单）：
  [`examples/verification-guide.md`](examples/verification-guide.md)
- **两会话剧本**（产品视角的对话演绎）：[`examples/two-session-playthrough.md`](examples/two-session-playthrough.md)
- **接口样例**：`contracts/round-request.example.json`、`contracts/round-result.example.json`
- **接口契约**：`API_CONTRACT.md`

跑一遍仓库自带的测试：

```powershell
$env:PYTHONPATH = "dify/ai-debate-show"
$env:PYTHONIOENCODING = "utf-8"
python -m unittest discover -s dify/ai-debate-show/tests -p "test_*.py" -v
```

在没有 Dify 的环境里，也可以只验证「Arena + PowerContext」这一段：
仓库带了一个只依赖标准库的联调脚本，它会对着**真实运行**的 Arena 与 PowerContext
跑一遍会话一写入、会话二召回，并把每一步断言打出来。

```powershell
$env:ARENA_BASE_URL        = "http://127.0.0.1:8088"
$env:POWERCONTEXT_BASE_URL = "http://127.0.0.1:8000"
python dify/ai-debate-show/scripts/verify-powercontext-e2e.py --scope-id <真实 scope_id>
```

脚本全部断言通过时退出码为 `0`，任何一步失败都会以非零退出码结束；
`scope_id` 必须由调用方提供，脚本不会替你猜。两局的 `game_id` 是固定的，
而 Arena 的会话只存在内存里，**重复运行前需要重启 Arena**。运行结果见
[`evidence/powercontext-e2e.md`](evidence/powercontext-e2e.md)。

## 已知限制

- **Arena 会话只在内存**：服务重启后当前对局消失，需要重新开始一局；PowerContext 的长期记忆不受影响。
- **同一个 Dify 会话只对应一局**：`game_id` 由会话标识派生，想再玩一次请新开会话。
- **一局最多三回合**：第三回合后必定结算，不会出现第四回合。
- **没有 PowerContext 就没有翻旧账**：这是设计上的降级，不是故障。
- **真实 Dify 降级三回合已验证**：Dify 1.17.1 已实际导入、发布并跑通三个回合；使用不存在的演示 Scope 时，第三回合按设计显示“结算（档案未入库）”。
- **真实 Dify + PowerContext 两会话翻旧账已验证**：同一可信 Scope 的会话一写入、会话二召回和主持人翻旧账均有运行记录（见 [`evidence/dify-e2e.md`](evidence/dify-e2e.md)）。
- **HTTP 节点的异常分支依赖 Dify 版本**：若目标 Dify 不支持 HTTP 节点的异常分支，对局台不可达时工作流会直接中断而不是落到降级回答。
- **模型不参与降级判定**：降级由服务返回的字段和 HTTP 状态码决定，模型只负责把既定事实说成节目语言。

## 不包含真实凭据

- 本仓库**不包含**任何真实 Token、密码、内网地址、账号或模型 Key。
- `.env.example` 里只有占位值；PowerContext 令牌只存在于运行者的环境变量或密钥存储中。
- Dify DSL 里没有任何 `Authorization` 头，认证由 Arena 服务端环境变量完成。
- 提交前建议自查：

```bash
rg -n "taskkill|kill -9|Bearer |sk-|ghp_" dify/ai-debate-show/README.md dify/ai-debate-show/.env.example dify/ai-debate-show/scripts dify/ai-debate-show/examples/verification-guide.md
```

这条命令在本文件里会命中它自己——因为命中的正是上面这行"被检索的字样"本身，属正常。
其余文件（`.env.example`、两个启动脚本、验收剧本）不应该有任何命中。
