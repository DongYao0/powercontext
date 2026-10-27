"""Arena 领域应用层：把内容层、对局状态机与 PowerContext 客户端组装成对局服务。

本层负责：

* 建立并维护一局游戏的会话状态；
* 在开局时准备历史记忆上下文；
* 推进回合并产出确定性反击卡素材；
* 在结算后写入经审核的游戏记忆。

本层**不生成任何模型文案**：主持人与对手的具体措辞由 Dify 侧的模型负责，
本层只提供卡片原文、追问、立场与回合状态。

会话只保存在内存中：服务重启后会话全部消失，玩家需要重新开始一局。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace

from .game import (
    GameInputError,
    GameState,
    RoundPlan,
    advance_round,
    start_game,
)
from .game_memory import GameMemoryEvent, GameMemoryRecorder
from .models import ContentCatalog
from .powercontext import PowerContextClient

__all__ = [
    "ArenaApplication",
    "ArenaApplicationError",
    "ArenaSession",
    "GameNotFoundError",
    "MemoryUnavailableError",
]

MEMORY_STATUS_READY = "ready"
MEMORY_STATUS_DEGRADED = "degraded"
PREPARE_MAX_BYTES = 4000


class ArenaApplicationError(RuntimeError):
    """对局状态冲突：重复创建、游戏已结束或重复写入同类记忆。"""


class GameNotFoundError(ArenaApplicationError):
    """指定的 game_id 不存在。"""


class MemoryUnavailableError(ArenaApplicationError):
    """未配置 PowerContext，记忆写入不可用。"""


@dataclass(frozen=True)
class ArenaSession:
    """一局游戏的会话快照，全部不可变。"""

    scope_id: str
    state: GameState
    memory_context: str | None
    memory_status: str
    topic_title: str
    recorded_memory_kinds: frozenset[str] = frozenset()


class ArenaApplication:
    """对局应用层。会话仓库的可变状态由锁保护。"""

    def __init__(
        self,
        catalog: ContentCatalog,
        powercontext_client: PowerContextClient | None,
    ) -> None:
        """构造应用层。

        Args:
            catalog: 已加载的节目内容目录。
            powercontext_client: 记忆客户端；为 ``None`` 表示未配置 PowerContext，
                此时记忆能力降级，但游戏主流程照常可用。
        """
        self._catalog = catalog
        self._client = powercontext_client
        self._recorder = GameMemoryRecorder(powercontext_client) if powercontext_client is not None else None
        self._sessions: dict[str, ArenaSession] = {}
        self._lock = threading.Lock()

    @property
    def powercontext_configured(self) -> bool:
        """是否配置了记忆客户端。未配置时记忆能力降级。"""
        return self._client is not None

    # ------------------------------------------------------------------ #
    # 创建游戏
    # ------------------------------------------------------------------ #

    def start_game(
        self,
        *,
        game_id: str,
        scope_id: str,
        player_nickname: str,
        topic_id: str,
        initial_stance: str,
        opponent_id: str,
    ) -> ArenaSession:
        """创建一局游戏并准备历史上下文。

        无论历史是否可用，只要参数合法，游戏都必须创建成功：
        记忆服务不可用时只降级为 ``memory_status="degraded"``，不会中断对局。

        Args:
            game_id: 本局标识，必须全局唯一。
            scope_id: 由可信调用方显式提供的 Scope 标识。
            player_nickname: 节目内昵称。
            topic_id: 辩题 id。
            initial_stance: 初始立场，支持或反对。
            opponent_id: 对手 id。

        Returns:
            新建的 :class:`ArenaSession`。

        Raises:
            GameInputError: 参数不合法。
            ArenaApplicationError: ``game_id`` 已被占用。
        """
        scope_id = _require_text(scope_id, "scope_id")
        game_id = _require_text(game_id, "game_id")

        with self._lock:
            if game_id in self._sessions:
                raise ArenaApplicationError(f"game_id {game_id!r} 已经存在，不能重复创建")

        state = start_game(
            self._catalog,
            game_id=game_id,
            player_nickname=player_nickname,
            topic_id=topic_id,
            initial_stance=initial_stance,
            opponent_id=opponent_id,
        )
        topic_title = self._catalog.topic(topic_id).title

        memory_context, memory_status = self._prepare_memory(
            scope_id=scope_id,
            topic_title=topic_title,
            initial_stance=initial_stance,
            player_nickname=player_nickname,
        )

        session = ArenaSession(
            scope_id=scope_id,
            state=state,
            memory_context=memory_context,
            memory_status=memory_status,
            topic_title=topic_title,
        )
        with self._lock:
            if game_id in self._sessions:
                raise ArenaApplicationError(f"game_id {game_id!r} 已经存在，不能重复创建")
            self._sessions[game_id] = session
        return session

    # ------------------------------------------------------------------ #
    # 推进回合
    # ------------------------------------------------------------------ #

    def play_round(
        self,
        *,
        game_id: str,
        player_action: str,
        player_message: str,
    ) -> RoundPlan:
        """推进一个回合并返回本回合计划。

        Args:
            game_id: 本局标识。
            player_action: 节目动作。
            player_message: 玩家本回合实际发言。

        Returns:
            :class:`~arena_service.game.RoundPlan`。

        Raises:
            GameNotFoundError: ``game_id`` 不存在。
            ArenaApplicationError: 本局已结束。
            GameInputError: 参数不合法。
        """
        with self._lock:
            session = self._require_session(game_id)
            if session.state.finished:
                raise ArenaApplicationError("本局已经结束，不能继续推进回合")

            plan = advance_round(
                self._catalog,
                state=session.state,
                player_action=player_action,
                player_message=player_message,
            )
            self._sessions[game_id] = replace(session, state=plan.state)
            return plan

    # ------------------------------------------------------------------ #
    # 写入结算记忆
    # ------------------------------------------------------------------ #

    def record_final_memory(
        self,
        *,
        game_id: str,
        player_message: str,
        memory_kind: str,
        memory_text: str,
        reason: str,
    ) -> None:
        """写入本局的结算记忆。

        只允许已结束的游戏写入；同一种 ``memory_kind`` 不允许重复写入。

        Args:
            game_id: 本局标识。
            player_message: 最后一个回合玩家实际发言。
            memory_kind: 记忆候选类型。
            memory_text: 记忆正文。
            reason: 写入理由。

        Raises:
            GameNotFoundError: ``game_id`` 不存在。
            ArenaApplicationError: 本局未结束，或同类记忆已经写过。
            MemoryUnavailableError: 未配置 PowerContext。
            GameMemoryValidationError: 记忆字段不满足写入策略。
            PowerContextError: 记忆写入失败，异常原样上抛。
        """
        with self._lock:
            session = self._require_session(game_id)
            if not session.state.finished:
                raise ArenaApplicationError("本局尚未结束，不能写入结算记忆")
            if memory_kind in session.recorded_memory_kinds:
                raise ArenaApplicationError(f"memory_kind {memory_kind!r} 的结算记忆已经写入过，不能重复写入")
            if self._recorder is None:
                raise MemoryUnavailableError("未配置 PowerContext，记忆写入不可用")

            # 先占位，避免并发下同一类型被写两次；写入失败会回滚占位。
            self._sessions[game_id] = replace(
                session,
                recorded_memory_kinds=session.recorded_memory_kinds | {memory_kind},
            )

        event = GameMemoryEvent(
            game_id=session.state.game_id,
            round_number=session.state.completed_rounds,
            player_nickname=session.state.player_nickname,
            topic_id=session.state.topic_id,
            topic_title=session.topic_title,
            final_stance=session.state.current_stance,
            player_message=player_message,
            memory_kind=memory_kind,
            memory_text=memory_text,
            reason=reason,
        )

        try:
            self._recorder.record(scope_id=session.scope_id, event=event)
        except Exception:
            with self._lock:
                current = self._sessions.get(game_id)
                if current is not None:
                    self._sessions[game_id] = replace(
                        current,
                        recorded_memory_kinds=current.recorded_memory_kinds - {memory_kind},
                    )
            raise

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #

    def _require_session(self, game_id: str) -> ArenaSession:
        """在持锁状态下取会话，不存在时抛出业务错误。"""
        session = self._sessions.get(game_id)
        if session is None:
            raise GameNotFoundError(f"game_id {game_id!r} 不存在")
        return session

    def _prepare_memory(
        self,
        *,
        scope_id: str,
        topic_title: str,
        initial_stance: str,
        player_nickname: str,
    ) -> tuple[str | None, str]:
        """准备历史上下文；任何失败都只降级，不影响游戏创建。"""
        if self._client is None:
            return None, MEMORY_STATUS_DEGRADED

        query = f"辩题：{topic_title}；当前立场：{initial_stance}；玩家：{player_nickname}"
        try:
            prepared = self._client.prepare_context(
                scope_id=scope_id,
                query=query,
                max_bytes=PREPARE_MAX_BYTES,
            )
        except Exception:
            return None, MEMORY_STATUS_DEGRADED

        if prepared.status == MEMORY_STATUS_READY and prepared.content is not None:
            return prepared.content, MEMORY_STATUS_READY
        return None, MEMORY_STATUS_DEGRADED


def _require_text(value: object, field: str) -> str:
    """要求非空、非纯空白字符串。"""
    if not isinstance(value, str):
        raise GameInputError(f"{field} 必须是字符串，实际为 {type(value).__name__}")
    if not value.strip():
        raise GameInputError(f"{field} 不能为空字符串或纯空白")
    return value
