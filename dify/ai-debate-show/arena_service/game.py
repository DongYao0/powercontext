"""《再说一遍？》三回合对局状态机。

本模块是纯领域逻辑：不依赖 Dify、模型、网络或 PowerContext。它只负责把
玩家输入与节目动作转换成确定性结果——本回合用哪张反击卡、当前立场是什么、
是否已经结算。主持人与对手的具体文案由上层模型生成，本模块只提供素材与约束。

状态机保证三件事：

* 一局最多三个回合，第三回合后必定结算，不会出现第四回合；
* 立场只由 ``switch_explain`` 翻转，其余动作保持不变；
* 卡片优先取未使用过的，全部用尽时按 T003 的规则受控复用。
"""

from __future__ import annotations

from dataclasses import dataclass

from .content import select_rebuttal_card
from .models import ContentCatalog

__all__ = [
    "GAME_ACTIONS",
    "GameFinishedError",
    "GameInputError",
    "GameState",
    "RoundPlan",
    "advance_round",
    "start_game",
]

GAME_ACTIONS = (
    "double_down",
    "switch_explain",
    "wild_card",
    "free_input",
)

ALLOWED_STANCES = ("支持", "反对")
MAX_ROUNDS = 3
STANCE_FLIPPING_ACTIONS = ("switch_explain",)


class GameInputError(ValueError):
    """对局输入不合法。"""


class GameFinishedError(RuntimeError):
    """对局已结束，不能继续推进回合。"""


@dataclass(frozen=True)
class GameState:
    """一局游戏的当前状态。"""

    game_id: str
    player_nickname: str
    topic_id: str
    opponent_id: str
    current_stance: str
    completed_rounds: int
    used_card_ids: tuple[str, ...]
    finished: bool


@dataclass(frozen=True)
class RoundPlan:
    """一个回合的推进结果。"""

    state: GameState
    round_number: int
    player_action: str
    player_message: str
    selected_card_id: str
    opponent_message: str
    follow_up_question: str
    card_reused: bool
    game_finished: bool


def start_game(
    catalog: ContentCatalog,
    *,
    game_id: str,
    player_nickname: str,
    topic_id: str,
    initial_stance: str,
    opponent_id: str,
) -> GameState:
    """开一局新游戏。

    Args:
        catalog: 已加载的节目内容目录，只读使用。
        game_id: 本局标识。
        player_nickname: 节目内昵称。
        topic_id: 辩题 id，必须存在于内容目录。
        initial_stance: 初始立场，只能是支持或反对。
        opponent_id: 对手 id，必须是角色为 opponent 的角色。

    Returns:
        初始 :class:`GameState`：零回合、未使用任何卡片、未结束。

    Raises:
        GameInputError: 参数不合法。错误文本包含出错的字段名。
    """
    game_id = _require_text(game_id, "game_id")
    player_nickname = _require_text(player_nickname, "player_nickname")
    topic_id = _require_text(topic_id, "topic_id")
    opponent_id = _require_text(opponent_id, "opponent_id")
    initial_stance = _require_stance(initial_stance, "initial_stance")
    _require_topic(catalog, topic_id)
    _require_opponent(catalog, opponent_id)

    return GameState(
        game_id=game_id,
        player_nickname=player_nickname,
        topic_id=topic_id,
        opponent_id=opponent_id,
        current_stance=initial_stance,
        completed_rounds=0,
        used_card_ids=(),
        finished=False,
    )


def advance_round(
    catalog: ContentCatalog,
    *,
    state: GameState,
    player_action: str,
    player_message: str,
) -> RoundPlan:
    """推进一个回合。

    Args:
        catalog: 已加载的节目内容目录，只读使用。
        state: 当前状态，不会被修改。
        player_action: 本回合的节目动作，必须属于 :data:`GAME_ACTIONS`。
        player_message: 玩家本回合实际说出的内容。

    Returns:
        本回合的 :class:`RoundPlan`，其中 ``state`` 是推进后的新状态。

    Raises:
        GameFinishedError: 本局已结束。
        GameInputError: 参数或状态不合法。错误文本包含出错的字段名。
    """
    if state.finished:
        raise GameFinishedError("本局已经结束，不能继续推进回合")

    player_action = _require_action(player_action)
    player_message = _require_text(player_message, "player_message")
    _require_topic(catalog, state.topic_id)
    _require_opponent(catalog, state.opponent_id)

    round_number = state.completed_rounds + 1
    if not 1 <= round_number <= MAX_ROUNDS:
        raise GameInputError(
            f"completed_rounds 为 {state.completed_rounds}，本回合编号 {round_number} 超出 1-{MAX_ROUNDS}"
        )

    stance = _resolve_stance(state.current_stance, player_action)
    selection = select_rebuttal_card(
        catalog,
        topic_id=state.topic_id,
        target_stance=stance,
        opponent_id=state.opponent_id,
        used_card_ids=state.used_card_ids,
    )
    card = selection.card

    new_state = GameState(
        game_id=state.game_id,
        player_nickname=state.player_nickname,
        topic_id=state.topic_id,
        opponent_id=state.opponent_id,
        current_stance=stance,
        completed_rounds=round_number,
        used_card_ids=state.used_card_ids + (card.id,),
        finished=round_number >= MAX_ROUNDS,
    )

    return RoundPlan(
        state=new_state,
        round_number=round_number,
        player_action=player_action,
        player_message=player_message,
        selected_card_id=card.id,
        opponent_message=card.card_text,
        follow_up_question=card.follow_up_question,
        card_reused=selection.reused,
        game_finished=new_state.finished,
    )


# --------------------------------------------------------------------------- #
# 内部辅助
# --------------------------------------------------------------------------- #


def _require_text(value: object, field: str) -> str:
    """要求非空、非纯空白字符串。"""
    if not isinstance(value, str):
        raise GameInputError(f"{field} 必须是字符串，实际为 {type(value).__name__}")
    if not value.strip():
        raise GameInputError(f"{field} 不能为空字符串或纯空白")
    return value


def _require_stance(value: object, field: str) -> str:
    """立场只能是支持或反对。"""
    if not isinstance(value, str):
        raise GameInputError(f"{field} 必须是字符串，实际为 {type(value).__name__}")
    if value not in ALLOWED_STANCES:
        raise GameInputError(f"{field} 只能是 '支持' 或 '反对'，实际为 {value!r}")
    return value


def _require_action(value: object) -> str:
    """节目动作必须属于 GAME_ACTIONS。"""
    if not isinstance(value, str):
        raise GameInputError(f"player_action 必须是字符串，实际为 {type(value).__name__}")
    if value not in GAME_ACTIONS:
        raise GameInputError(f"player_action 只能是 {list(GAME_ACTIONS)} 之一，实际为 {value!r}")
    return value


def _require_topic(catalog: ContentCatalog, topic_id: str) -> None:
    """辩题必须存在于内容目录。"""
    if topic_id not in catalog.topics:
        raise GameInputError(f"topic_id {topic_id!r} 不存在于内容目录")


def _require_opponent(catalog: ContentCatalog, opponent_id: str) -> None:
    """对手必须是内容目录中角色为 opponent 的角色。"""
    character = catalog.characters.get(opponent_id)
    if character is None:
        raise GameInputError(f"opponent_id {opponent_id!r} 不存在于内容目录")
    if character.role != "opponent":
        raise GameInputError(f"opponent_id {opponent_id!r} 的角色是 {character.role!r}，必须是 'opponent'")


def _resolve_stance(current_stance: str, player_action: str) -> str:
    """只有 switch_explain 会翻转立场，其余动作保持不变。"""
    if player_action in STANCE_FLIPPING_ACTIONS:
        return "反对" if current_stance == "支持" else "支持"
    return current_stance
