"""《再说一遍？》游戏记忆策略层与 PowerContext 写入适配。

本模块把一条已经判定值得保存的游戏记忆，转换为一次可审计的
``record_memory(...)`` 调用：先完成全部写入前校验，再构造稳定的来源标识、
证据正文与元数据，最后恰好调用一次客户端。

本模块不创建、猜测或持久化 Scope——``scope_id`` 永远来自可信调用方。
本模块也不吞掉客户端抛出的异常，包括"来源已存、记忆未存"的部分成功状态。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "ALLOWED_MEMORY_KINDS",
    "MEMORY_TEXT_MAX_UTF8_BYTES",
    "REASON_MAX_LENGTH",
    "SCOPE_ID_MAX_LENGTH",
    "SOURCE_ID_MAX_LENGTH",
    "GameMemoryEvent",
    "GameMemoryRecorder",
    "GameMemoryValidationError",
]

ALLOWED_MEMORY_KINDS = frozenset({
    "stance",
    "quote",
    "persona",
    "promise",
    "reversal",
    "catchphrase",
})

MEMORY_TEXT_MAX_UTF8_BYTES = 8192

# 以下上限来自 PowerContext 的 HTTP 契约（openapi/powercontext.yaml）。
# 提前在策略层拒绝，可以避免"来源已保存、记忆写入 422"的部分成功状态。
SCOPE_ID_MAX_LENGTH = 256
SOURCE_ID_MAX_LENGTH = 256
REASON_MAX_LENGTH = 512

APPLICATION_NAME = "ai-debate-show"
ALLOWED_STANCES = ("支持", "反对")
ALLOWED_ROUND_NUMBERS = (1, 2, 3)
PRINTABLE_ASCII_LOWEST = "!"
PRINTABLE_ASCII_HIGHEST = "~"


class GameMemoryValidationError(ValueError):
    """游戏记忆事件不符合可安全写入的策略。"""


@dataclass(frozen=True)
class GameMemoryEvent:
    """一条已审核、值得长期保存的游戏记忆事件。

    本数据类只承载数据，不做校验；校验发生在
    :meth:`GameMemoryRecorder.record` 中，且发生在任何远程写入之前。
    """

    game_id: str
    round_number: int
    player_nickname: str
    topic_id: str
    topic_title: str
    final_stance: str
    player_message: str
    memory_kind: str
    memory_text: str
    reason: str


class MemoryWriter(Protocol):
    """记录器所需的最小写入边界。

    任何具备该调用形态的对象都可以注入，不必是具体的 PowerContext 客户端。
    """

    def record_memory(
        self,
        *,
        scope_id: str,
        source_id: str,
        source_content: str,
        metadata: Mapping[str, object],
        memory_kind: str,
        memory_text: str,
        reason: str,
    ) -> None:
        """保存来源证据并写入长期记忆。"""
        ...


class GameMemoryRecorder:
    """把游戏记忆事件转成一次可审计的 PowerContext 写入。"""

    def __init__(self, client: MemoryWriter) -> None:
        self._client = client

    def record(self, *, scope_id: str, event: GameMemoryEvent) -> None:
        """校验并记录一条游戏记忆。

        校验全部通过后才会调用客户端，且恰好调用一次。任何校验失败时，
        客户端调用次数为零。

        除字段取值外，还会按 PowerContext 的服务端契约预检长度与字符集：
        ``scope_id`` 与 ``reason`` 不得超过各自上限，``game_id`` 只能含可打印
        ASCII，组合出的 ``source_id`` 不得超过上限。这样可以避免"来源已保存、
        记忆写入 422"的部分成功状态。

        Args:
            scope_id: 由可信调用方显式提供的 Scope 标识。
            event: 已审核的游戏记忆事件。

        Raises:
            TypeError: 参数类型不正确。
            GameMemoryValidationError: 取值、枚举或长度不符合写入策略。
            Exception: 客户端抛出的异常原样向上传递，不做捕获或转换。
        """
        scope_id = _require_text(scope_id, "scope_id")
        _require_max_length(scope_id, SCOPE_ID_MAX_LENGTH, "scope_id")
        game_id = _require_text(event.game_id, "game_id")
        _require_printable_ascii(game_id, "game_id")
        player_nickname = _require_text(event.player_nickname, "player_nickname")
        topic_id = _require_text(event.topic_id, "topic_id")
        topic_title = _require_text(event.topic_title, "topic_title")
        player_message = _require_text(event.player_message, "player_message")
        memory_text = _require_text(event.memory_text, "memory_text")
        reason = _require_text(event.reason, "reason")
        _require_max_length(reason, REASON_MAX_LENGTH, "reason")
        round_number = _require_round_number(event.round_number)
        final_stance = _require_stance(event.final_stance)
        memory_kind = _require_memory_kind(event.memory_kind)
        _require_memory_text_length(memory_text)

        source_id = f"{APPLICATION_NAME}:{game_id}:round:{round_number}:memory:{memory_kind}"
        _require_max_length(source_id, SOURCE_ID_MAX_LENGTH, "source_id")
        source_content = (
            f"玩家昵称：{player_nickname}\n"
            f"辩题：{topic_title}（{topic_id}）\n"
            f"回合：{round_number}\n"
            f"本局结束立场：{final_stance}\n"
            f"玩家发言：{player_message}\n"
            f"记忆候选（{memory_kind}）：{memory_text}\n"
            f"写入理由：{reason}"
        )
        metadata = {
            "application": APPLICATION_NAME,
            "game_id": game_id,
            "round_number": round_number,
            "topic_id": topic_id,
            "memory_kind": memory_kind,
        }

        self._client.record_memory(
            scope_id=scope_id,
            source_id=source_id,
            source_content=source_content,
            metadata=metadata,
            memory_kind=memory_kind,
            memory_text=memory_text,
            reason=reason,
        )


# --------------------------------------------------------------------------- #
# 写入前校验
# --------------------------------------------------------------------------- #


def _require_text(value: object, field: str) -> str:
    """要求非空、非纯空白字符串；原样返回，不改写调用方传入的值。"""
    if not isinstance(value, str):
        raise TypeError(f"{field} 必须是字符串，实际为 {type(value).__name__}")
    if not value.strip():
        raise GameMemoryValidationError(f"{field} 不能为空字符串或纯空白")
    return value


def _require_max_length(value: str, limit: int, field: str) -> None:
    """要求字符数不超过上限；超限时拒绝，绝不截断。"""
    if len(value) > limit:
        raise GameMemoryValidationError(f"{field} 长度为 {len(value)} 字符，超过上限 {limit} 字符；不允许截断写入")


def _require_printable_ascii(value: str, field: str) -> None:
    """要求只含可打印 ASCII（``!`` 到 ``~``），不含空格、中文与控制字符。"""
    for index, character in enumerate(value):
        if not PRINTABLE_ASCII_LOWEST <= character <= PRINTABLE_ASCII_HIGHEST:
            raise GameMemoryValidationError(
                f"{field} 只能包含可打印 ASCII 字符"
                f"（{PRINTABLE_ASCII_LOWEST} 到 {PRINTABLE_ASCII_HIGHEST}），"
                f"第 {index + 1} 个字符 {character!r} 不符合"
            )


def _require_round_number(value: object) -> int:
    """回合序号必须是 1、2、3 之一；布尔值不算整数。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"round_number 必须是整数 1-3（布尔值不算整数），实际为 {type(value).__name__}")
    if value not in ALLOWED_ROUND_NUMBERS:
        raise GameMemoryValidationError(f"round_number 必须是 1、2 或 3，实际为 {value}")
    return value


def _require_stance(value: object) -> str:
    """本局结束立场只能是支持或反对。"""
    if not isinstance(value, str):
        raise TypeError(f"final_stance 必须是字符串，实际为 {type(value).__name__}")
    if value not in ALLOWED_STANCES:
        raise GameMemoryValidationError(f"final_stance 只能是 '支持' 或 '反对'，实际为 {value!r}")
    return value


def _require_memory_kind(value: object) -> str:
    """记忆候选类型必须在允许集合内。"""
    if not isinstance(value, str):
        raise TypeError(f"memory_kind 必须是字符串，实际为 {type(value).__name__}")
    if value not in ALLOWED_MEMORY_KINDS:
        raise GameMemoryValidationError(f"memory_kind 只能是 {sorted(ALLOWED_MEMORY_KINDS)} 之一，实际为 {value!r}")
    return value


def _require_memory_text_length(memory_text: str) -> None:
    """记忆正文不得超过 8192 UTF-8 字节；超长时拒绝，绝不截断。"""
    size = len(memory_text.encode("utf-8"))
    if size > MEMORY_TEXT_MAX_UTF8_BYTES:
        raise GameMemoryValidationError(
            f"memory_text 的 UTF-8 长度为 {size} 字节，超过上限 {MEMORY_TEXT_MAX_UTF8_BYTES} 字节；不允许截断写入"
        )
