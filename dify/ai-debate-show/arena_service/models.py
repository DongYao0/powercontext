"""《再说一遍？》节目内容资产的不可变领域模型。

本模块只定义数据结构与查询能力，不读取文件、不做卡片选择。
加载与选择逻辑见 :mod:`arena_service.content`。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

__all__ = [
    "CardSelection",
    "Character",
    "ContentCatalog",
    "RebuttalCard",
    "Topic",
]


@dataclass(frozen=True)
class Topic:
    """一个荒诞辩题。"""

    id: str
    title: str
    question: str
    tags: tuple[str, ...]
    stances: tuple[str, ...]
    opening_hint: str
    memory_hook: str


@dataclass(frozen=True)
class Character:
    """一个节目角色（主持人或对手）。"""

    id: str
    name: str
    role: str
    voice: str
    game_function: str
    must_do: tuple[str, ...]
    must_not_do: tuple[str, ...]


@dataclass(frozen=True)
class RebuttalCard:
    """一张可被对手直接采用的反击卡。"""

    id: str
    topic_id: str
    target_stance: str
    opponent_id: str
    trigger_type: str
    card_text: str
    follow_up_question: str
    memory_follow_up: str | None
    weight: int


@dataclass(frozen=True)
class CardSelection:
    """一次反击卡选择的结果。

    ``reused`` 为 ``True`` 表示所有候选卡都已被使用过，本次按约定复用了排序第一张。
    """

    card: RebuttalCard
    reused: bool


@dataclass(frozen=True)
class ContentCatalog:
    """已验证的节目内容目录。

    三个映射都以只读代理保存，外部无法修改内部状态。
    """

    topics: Mapping[str, Topic]
    characters: Mapping[str, Character]
    cards: Mapping[str, RebuttalCard]

    def __post_init__(self) -> None:
        object.__setattr__(self, "topics", MappingProxyType(dict(self.topics)))
        object.__setattr__(self, "characters", MappingProxyType(dict(self.characters)))
        object.__setattr__(self, "cards", MappingProxyType(dict(self.cards)))

    def topic(self, topic_id: str) -> Topic:
        """按 ID 取辩题，不存在时抛出带明确说明的 ``KeyError``。"""
        try:
            return self.topics[topic_id]
        except KeyError:
            raise KeyError(f"未知辩题 id：{topic_id!r}") from None

    def character(self, character_id: str) -> Character:
        """按 ID 取角色，不存在时抛出带明确说明的 ``KeyError``。"""
        try:
            return self.characters[character_id]
        except KeyError:
            raise KeyError(f"未知角色 id：{character_id!r}") from None

    def card(self, card_id: str) -> RebuttalCard:
        """按 ID 取反击卡，不存在时抛出带明确说明的 ``KeyError``。"""
        try:
            return self.cards[card_id]
        except KeyError:
            raise KeyError(f"未知反击卡 id：{card_id!r}") from None

    def cards_for(
        self,
        *,
        topic_id: str,
        target_stance: str,
        opponent_id: str,
    ) -> tuple[RebuttalCard, ...]:
        """返回匹配给定条件的反击卡，按 ``id`` 升序排列。

        这是一个纯查询：不改变目录状态，也不决定最终选哪一张。
        """
        matched = (
            card
            for card in self.cards.values()
            if card.topic_id == topic_id and card.target_stance == target_stance and card.opponent_id == opponent_id
        )
        return tuple(sorted(matched, key=lambda card: card.id))
