#!/usr/bin/env python3
"""真实 PowerContext 两会话「翻旧账」联调验证脚本。

本脚本只做一件事：对着**真实运行**的 Arena HTTP 服务与**真实运行**的
PowerContext Server，跑一遍完整的「会话一写入 → 会话二召回」链路，
并用断言把结果钉死。

设计约束：

* 只使用 Python 标准库，不依赖 requests / pytest / httpx；
* 不导入 ``arena_service`` 内部模块，全部通过 HTTP 交互，避免自证；
* ``scope_id`` 必须由命令行或环境传入，脚本内不写死任何 Scope；
* 所有输出先脱敏，Bearer 令牌不会出现在终端或日志里；
* 任一步失败即以非零退出码结束，不做「看起来成功」的兜底。

用法::

    export ARENA_BASE_URL=http://127.0.0.1:8088
    export POWERCONTEXT_BASE_URL=http://127.0.0.1:8000
    python scripts/verify-powercontext-e2e.py --scope-id <真实 scope_id>

退出码：0 表示全部断言通过；1 表示存在失败断言；2 表示参数或环境不完整。

注意：两局的 ``game_id`` 是固定的，而 Arena 的会话只保存在内存。
重复运行前需要**重启 Arena**，否则建局会撞上已存在的 ``game_id``。
写入用的 ``source_id`` 是确定性的，所以重放同一局不会在 PowerContext 里
产生重复的记忆条目。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

REDACTED = "***"

SESSION_ONE_GAME_ID = "pc-e2e-session-one"
SESSION_TWO_GAME_ID = "pc-e2e-session-two"
PLAYER_NICKNAME = "阿强"
TOPIC_ID = "pearl-voting-rights"
OPPONENT_ID = "logic-monster"
SESSION_ONE_STANCE = "反对"
SESSION_TWO_STANCE = "支持"

PLAYER_MESSAGE = "珍珠没有手，所以不能投票。"
MEMORY_TEXT = "阿强在珍珠投票权一局最终反对，理由是珍珠没有手。"
MEMORY_REASON = "记录本局最终立场，供后续同题改口时翻旧账。"
MEMORY_KIND = "stance"

# 会话二的召回内容必须命中其中至少一个关键词，才算真的翻到了旧账。
RECALL_KEYWORDS = ("反对", "珍珠", "没有手")

DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_BODY_CHARS = 1200

# 运行期收集到的敏感值；打印任何内容前统一替换。
_SECRETS: list[str] = []


class E2EError(RuntimeError):
    """联调流程中的断言失败或调用失败。"""


# --------------------------------------------------------------------------- #
# 脱敏
# --------------------------------------------------------------------------- #


def register_secret(value: str | None) -> None:
    """登记一个需要在输出中隐藏的值。"""
    if value and value.strip():
        _SECRETS.append(value.strip())


def redact(text: str) -> str:
    """把已登记的敏感值替换掉。"""
    for secret in _SECRETS:
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text


def mask_identifier(value: str) -> str:
    """给标识符做轻量遮罩，只保留首尾少量字符。"""
    text = value.strip()
    if len(text) <= 10:
        return text[:3] + "…"
    return f"{text[:8]}…{text[-4:]}"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


class HttpResponse:
    """一次 HTTP 调用的结果。"""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body

    def json(self) -> Any:
        """把响应体解析成 JSON 对象。"""
        try:
            return json.loads(self.body)
        except json.JSONDecodeError as exc:
            raise E2EError(
                f"响应不是合法 JSON（{exc.msg}）；响应体前 {MAX_BODY_CHARS} 字符：{redact(self.body[:MAX_BODY_CHARS])}"
            ) from exc


def http_request(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> HttpResponse:
    """发送一次 JSON 请求并返回响应；HTTP 错误码也作为结果返回。"""
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return HttpResponse(exc.code, raw)
    except urllib.error.URLError as exc:
        raise E2EError(f"网络错误：{redact(str(exc.reason))}（{url}）") from exc
    except TimeoutError as exc:
        raise E2EError(f"请求超时（{timeout} 秒）：{url}") from exc


def http_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, Any]:
    """发送请求并要求 2xx 与 JSON 对象。"""
    response = http_request(method=method, url=url, payload=payload, token=token, timeout=timeout)
    document = response.json()
    if not 200 <= response.status <= 299:
        raise E2EError(
            f"{method} {url} 返回 HTTP {response.status}；"
            f"响应体前 {MAX_BODY_CHARS} 字符：{redact(response.body[:MAX_BODY_CHARS])}"
        )
    if not isinstance(document, dict):
        raise E2EError(f"{method} {url} 的响应顶层不是 JSON 对象")
    return response.status, document


# --------------------------------------------------------------------------- #
# 步骤
# --------------------------------------------------------------------------- #


def step(message: str) -> None:
    """打印一个步骤标题。"""
    print(f"[步骤] {redact(message)}")


def ok(message: str) -> None:
    """打印一条通过的检查结果。"""
    print(f"  [通过] {redact(message)}")


def check_health(arena_base: str, token: str | None) -> None:
    """检查 Arena 服务健康状态与记忆能力。"""
    step("检查 Arena /health")
    status, document = http_json(method="GET", url=f"{arena_base}/health", token=token)
    if status != 200:
        raise E2EError(f"/health 返回 HTTP {status}")
    if document.get("status") != "ok":
        raise E2EError(f"/health 的 status 不是 'ok'：{document.get('status')!r}")
    memory_configured = document.get("memory_configured")
    if memory_configured is not True:
        raise E2EError("Arena 的 memory_configured 不是 true，说明它没有连接真实 PowerContext；本次联调不成立")
    ok(f"Arena /health = 200，status=ok，memory_configured={memory_configured}")


def check_powercontext(powercontext_base: str, scope_id: str, token: str | None) -> None:
    """确认 PowerContext 实例可达，且传入的 scope_id 真实存在。"""
    step(f"确认 PowerContext 实例可达（{powercontext_base}）")
    status, document = http_json(
        method="GET",
        url=f"{powercontext_base}/v1/scopes/{scope_id}",
        token=token,
    )
    if status != 200:
        raise E2EError(f"读取 Scope 返回 HTTP {status}")
    real_scope_id = document.get("scope_id")
    if real_scope_id != scope_id:
        raise E2EError(f"Scope 不匹配：请求 {mask_identifier(scope_id)}，响应 {mask_identifier(str(real_scope_id))}")
    ok(
        f"Scope {mask_identifier(scope_id)} 存在"
        f"（title={redact(str(document.get('title')))}，version={document.get('version')}）"
    )


def create_game(
    *,
    arena_base: str,
    game_id: str,
    scope_id: str,
    initial_stance: str,
    token: str | None,
) -> dict[str, Any]:
    """创建一局游戏，返回 Arena 的响应体。"""
    status, document = http_json(
        method="POST",
        url=f"{arena_base}/games",
        payload={
            "game_id": game_id,
            "scope_id": scope_id,
            "player_nickname": PLAYER_NICKNAME,
            "topic_id": TOPIC_ID,
            "initial_stance": initial_stance,
            "opponent_id": OPPONENT_ID,
        },
        token=token,
    )
    if status != 201:
        raise E2EError(f"创建游戏 {game_id} 返回 HTTP {status}，期望 201")
    return document


def play_round(
    *,
    arena_base: str,
    game_id: str,
    player_action: str,
    player_message: str,
    token: str | None,
) -> dict[str, Any]:
    """推进一个回合。"""
    status, document = http_json(
        method="POST",
        url=f"{arena_base}/games/{game_id}/rounds",
        payload={"player_action": player_action, "player_message": player_message},
        token=token,
    )
    if status != 200:
        raise E2EError(f"推进回合 {game_id} 返回 HTTP {status}")
    return document


def record_memory(
    *,
    arena_base: str,
    game_id: str,
    token: str | None,
) -> dict[str, Any]:
    """写入结算记忆。"""
    status, document = http_json(
        method="POST",
        url=f"{arena_base}/games/{game_id}/memory",
        payload={
            "player_message": PLAYER_MESSAGE,
            "memory_kind": MEMORY_KIND,
            "memory_text": MEMORY_TEXT,
            "reason": MEMORY_REASON,
        },
        token=token,
    )
    if status != 200:
        raise E2EError(f"写入记忆 {game_id} 返回 HTTP {status}")
    return document


def run_session_one(
    *,
    arena_base: str,
    scope_id: str,
    token: str | None,
) -> None:
    """会话一：三回合 double_down 后写入结算记忆。"""
    step(f"会话一：创建 {SESSION_ONE_GAME_ID}（立场={SESSION_ONE_STANCE}）")
    created = create_game(
        arena_base=arena_base,
        game_id=SESSION_ONE_GAME_ID,
        scope_id=scope_id,
        initial_stance=SESSION_ONE_STANCE,
        token=token,
    )
    if created.get("memory_context"):
        print("  [提示] 该 Scope 已有历史（可能是重复运行），会话一的「无历史」断言不作为本次结论依据")
    ok(
        f"创建成功（HTTP 201），memory_status="
        f"{created.get('memory_status')!r}，memory_context="
        f"{'空' if not created.get('memory_context') else '非空'}"
    )

    for round_number in (1, 2, 3):
        step(f"会话一：第 {round_number} 回合 double_down")
        plan = play_round(
            arena_base=arena_base,
            game_id=SESSION_ONE_GAME_ID,
            player_action="double_down",
            player_message=PLAYER_MESSAGE,
            token=token,
        )
        state = plan.get("state") if isinstance(plan.get("state"), dict) else {}
        finished = plan.get("game_finished", state.get("finished"))
        ok(f"第 {round_number} 回合完成（completed_rounds={state.get('completed_rounds')}，game_finished={finished}）")

    step("会话一：写入结算记忆")
    document = record_memory(arena_base=arena_base, game_id=SESSION_ONE_GAME_ID, token=token)
    if document.get("status") != "recorded":
        raise E2EError(f"写入记忆返回的 status 不是 'recorded'：{document.get('status')!r}")
    ok("记忆写入成功，响应 status='recorded'")


def run_session_two(
    *,
    arena_base: str,
    scope_id: str,
    token: str | None,
) -> None:
    """会话二：同 Scope 改口，断言召回上一局记忆。"""
    step(f"会话二：创建 {SESSION_TWO_GAME_ID}（同一 Scope，立场={SESSION_TWO_STANCE}）")
    status, document = http_json(
        method="POST",
        url=f"{arena_base}/games",
        payload={
            "game_id": SESSION_TWO_GAME_ID,
            "scope_id": scope_id,
            "player_nickname": PLAYER_NICKNAME,
            "topic_id": TOPIC_ID,
            "initial_stance": SESSION_TWO_STANCE,
            "opponent_id": OPPONENT_ID,
        },
        token=token,
    )
    if status != 201:
        raise E2EError(f"创建游戏 {SESSION_TWO_GAME_ID} 返回 HTTP {status}，期望 201")
    ok("创建成功（HTTP 201）")

    memory_status = document.get("memory_status")
    if memory_status != "ready":
        raise E2EError(f"会话二的 memory_status 不是 'ready'，实际为 {memory_status!r}；说明上一局记忆没有被召回")
    ok("memory_status='ready'")

    memory_context = document.get("memory_context")
    if not isinstance(memory_context, str) or not memory_context.strip():
        raise E2EError("会话二的 memory_context 不是非空字符串")
    ok(f"memory_context 为非空字符串（{len(memory_context)} 字符）")

    hits = [keyword for keyword in RECALL_KEYWORDS if keyword in memory_context]
    if not hits:
        raise E2EError(
            "会话二的 memory_context 没有命中会话一的立场/论点关键词"
            f"（期望包含 {list(RECALL_KEYWORDS)} 之一）；"
            f"实际内容：{redact(memory_context[:MAX_BODY_CHARS])}"
        )
    ok(f"memory_context 命中会话一关键词：{'、'.join(hits)}")
    print(f"  召回内容摘要：{redact(memory_context[:300])}")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
    parser = argparse.ArgumentParser(
        description="真实 PowerContext 两会话「翻旧账」联调验证",
    )
    parser.add_argument(
        "--scope-id",
        default=os.environ.get("POWERCONTEXT_SCOPE_ID"),
        help="要使用的真实 scope_id；缺省时读取环境变量 POWERCONTEXT_SCOPE_ID",
    )
    parser.add_argument(
        "--arena-base-url",
        default=os.environ.get("ARENA_BASE_URL"),
        help="Arena 根地址；缺省时读取环境变量 ARENA_BASE_URL",
    )
    parser.add_argument(
        "--powercontext-base-url",
        default=os.environ.get("POWERCONTEXT_BASE_URL"),
        help="PowerContext 根地址；缺省时读取环境变量 POWERCONTEXT_BASE_URL",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"单次请求超时秒数，默认 {DEFAULT_TIMEOUT_SECONDS}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行联调流程；返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    arena_base = (args.arena_base_url or "").strip().rstrip("/")
    powercontext_base = (args.powercontext_base_url or "").strip().rstrip("/")
    scope_id = (args.scope_id or "").strip()
    token = (os.environ.get("POWERCONTEXT_BEARER_TOKEN") or "").strip() or None
    register_secret(token)

    missing = [
        name
        for name, value in (
            ("--scope-id / POWERCONTEXT_SCOPE_ID", scope_id),
            ("--arena-base-url / ARENA_BASE_URL", arena_base),
            ("--powercontext-base-url / POWERCONTEXT_BASE_URL", powercontext_base),
        )
        if not value
    ]
    if missing:
        print("[参数缺失] 需要：" + "；".join(missing), file=sys.stderr)
        return 2

    print("=" * 72)
    print("《再说一遍？AI 记仇辩论夜》真实 PowerContext 两会话联调")
    print(f"  Arena        : {arena_base}")
    print(f"  PowerContext : {powercontext_base}")
    print(f"  Scope        : {mask_identifier(scope_id)}")
    print("=" * 72)

    try:
        check_health(arena_base, token)
        check_powercontext(powercontext_base, scope_id, token)
        run_session_one(arena_base=arena_base, scope_id=scope_id, token=token)
        run_session_two(arena_base=arena_base, scope_id=scope_id, token=token)
    except E2EError as exc:
        print(f"[失败] {redact(str(exc))}", file=sys.stderr)
        return 1

    print("-" * 72)
    print("结论：会话一已真实写入 PowerContext，会话二在同一 Scope 下被真实召回。")
    print("-" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
