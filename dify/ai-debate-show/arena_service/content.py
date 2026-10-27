"""节目内容资产的加载、验证与确定性反击卡选择。

本模块不依赖网络、模型、数据库或任何外部服务，只读取本地 JSON 文件。
内容资产不符合已冻结契约时一律抛出 :class:`ContentValidationError`，
不做静默降级，也不猜测默认值。
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

from .models import CardSelection, Character, ContentCatalog, RebuttalCard, Topic

__all__ = [
    "ContentValidationError",
    "NoMatchingCardError",
    "load_content_catalog",
    "select_rebuttal_card",
]

TOPICS_FILE = "topics.json"
CHARACTERS_FILE = "characters.json"
CARDS_FILE = "rebuttal_cards.draft.json"

EXPECTED_VERSION = "0.1"
REQUIRED_STANCES = ("支持", "反对")
VALID_TRIGGER_TYPES = frozenset({"logic_gap", "reversal", "exaggeration", "wordplay"})
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MIN_CARDS_PER_TOPIC = 6
MIN_CARDS_PER_STANCE = 3
REQUIRED_OPPONENTS = ("logic-monster", "contrarian")


class ContentValidationError(ValueError):
    """内容资产不符合已冻结契约时抛出。"""


class NoMatchingCardError(LookupError):
    """找不到符合当前回合条件的反击卡时抛出。"""


def load_content_catalog(content_directory: Path) -> ContentCatalog:
    """读取 topics.json、characters.json 和 rebuttal_cards.draft.json。

    Args:
        content_directory: 内容资产所在目录。

    Returns:
        验证通过的只读 :class:`~arena_service.models.ContentCatalog`。

    Raises:
        ContentValidationError: 文件缺失、无法解析，或任何一条契约校验失败。
    """
    directory = Path(content_directory)
    if not directory.is_dir():
        raise ContentValidationError(f"内容目录不存在或不是目录：{directory}")

    topics = _load_topics(_read_json_object(directory / TOPICS_FILE, TOPICS_FILE), TOPICS_FILE)
    characters = _load_characters(_read_json_object(directory / CHARACTERS_FILE, CHARACTERS_FILE), CHARACTERS_FILE)
    cards = _load_cards(_read_json_object(directory / CARDS_FILE, CARDS_FILE), CARDS_FILE, topics, characters)
    return ContentCatalog(topics=topics, characters=characters, cards=cards)


def select_rebuttal_card(
    catalog: ContentCatalog,
    *,
    topic_id: str,
    target_stance: str,
    opponent_id: str,
    used_card_ids: Collection[str],
) -> CardSelection:
    """按冻结规则确定性选择一张反击卡。

    候选条件为 ``topic_id``、``target_stance``、``opponent_id`` 同时匹配；
    候选按 ``card.id`` 升序排列，优先返回第一张未被使用过的卡，
    全部用过时按约定复用排序第一张并置 ``reused=True``。

    Args:
        catalog: 已加载的内容目录。
        topic_id: 当前辩题 id。
        target_stance: 玩家立场，取 ``支持`` 或 ``反对``。
        opponent_id: 当前对手 id。
        used_card_ids: 本局已使用过的卡片 id，仅作为只读输入。

    Returns:
        :class:`~arena_service.models.CardSelection`。

    Raises:
        NoMatchingCardError: 没有任何候选卡。
    """
    candidates = catalog.cards_for(
        topic_id=topic_id,
        target_stance=target_stance,
        opponent_id=opponent_id,
    )
    if not candidates:
        raise NoMatchingCardError(
            "没有符合当前回合条件的反击卡："
            f"topic_id={topic_id!r}, target_stance={target_stance!r}, opponent_id={opponent_id!r}"
        )

    used = frozenset(used_card_ids)
    for card in candidates:
        if card.id not in used:
            return CardSelection(card=card, reused=False)
    return CardSelection(card=candidates[0], reused=True)


# --------------------------------------------------------------------------- #
# 文件读取
# --------------------------------------------------------------------------- #


def _read_json_object(path: Path, file_name: str) -> dict[str, Any]:
    """读取一个 JSON 文件并确认顶层是对象。"""
    if not path.is_file():
        raise ContentValidationError(f"{file_name}: 内容目录中不存在该文件（{path}）")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContentValidationError(f"{file_name}: 无法读取文件（{exc}）") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContentValidationError(
            f"{file_name}: JSON 解析失败（第 {exc.lineno} 行第 {exc.colno} 列）：{exc.msg}"
        ) from exc
    if not isinstance(document, dict):
        raise ContentValidationError(f"{file_name}: 顶层结构必须是 JSON 对象，实际为 {type(document).__name__}")
    return document


# --------------------------------------------------------------------------- #
# 顶层结构校验
# --------------------------------------------------------------------------- #


def _require_version(document: dict[str, Any], file_name: str) -> None:
    if "version" not in document:
        raise ContentValidationError(f"{file_name}: 缺少顶层字段 'version'")
    version = document["version"]
    if version != EXPECTED_VERSION:
        raise ContentValidationError(
            f"{file_name}: 顶层字段 'version' 必须为字符串 {EXPECTED_VERSION!r}，实际为 {version!r}"
        )


def _require_entries(document: dict[str, Any], field: str, file_name: str) -> list[Any]:
    if field not in document:
        raise ContentValidationError(f"{file_name}: 缺少顶层数组字段 '{field}'")
    entries = document[field]
    if not isinstance(entries, list):
        raise ContentValidationError(f"{file_name}: 顶层字段 '{field}' 必须是数组，实际为 {type(entries).__name__}")
    return entries


# --------------------------------------------------------------------------- #
# 字段校验
# --------------------------------------------------------------------------- #


def _require_id(entry: dict[str, Any], file_name: str, category: str) -> str:
    if "id" not in entry:
        raise ContentValidationError(f"{file_name}: {category} 缺少必需字段 'id'")
    value = entry["id"]
    if not isinstance(value, str) or not value.strip():
        raise ContentValidationError(f"{file_name}: {category} 的字段 'id' 必须是非空字符串，实际为 {value!r}")
    return value


def _require_text(entry: dict[str, Any], field: str, file_name: str, category: str, ident: str) -> str:
    if field not in entry:
        raise ContentValidationError(f"{file_name}: {category} {ident!r} 缺少必需字段 '{field}'")
    value = entry[field]
    if not isinstance(value, str):
        raise ContentValidationError(
            f"{file_name}: {category} {ident!r} 的字段 '{field}' 必须是字符串，实际为 {type(value).__name__}"
        )
    if not value.strip():
        raise ContentValidationError(f"{file_name}: {category} {ident!r} 的字段 '{field}' 不能为空字符串")
    return value


def _require_str_tuple(entry: dict[str, Any], field: str, file_name: str, category: str, ident: str) -> tuple[str, ...]:
    if field not in entry:
        raise ContentValidationError(f"{file_name}: {category} {ident!r} 缺少必需字段 '{field}'")
    value = entry[field]
    if not isinstance(value, list):
        raise ContentValidationError(
            f"{file_name}: {category} {ident!r} 的字段 '{field}' 必须是数组，实际为 {type(value).__name__}"
        )
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ContentValidationError(
                f"{file_name}: {category} {ident!r} 的字段 '{field}' 第 {index} 项必须是非空字符串，实际为 {item!r}"
            )
    return tuple(value)


# --------------------------------------------------------------------------- #
# 各类内容
# --------------------------------------------------------------------------- #


def _load_topics(document: dict[str, Any], file_name: str) -> dict[str, Topic]:
    _require_version(document, file_name)
    topics: dict[str, Topic] = {}
    for index, entry in enumerate(_require_entries(document, "topics", file_name)):
        if not isinstance(entry, dict):
            raise ContentValidationError(
                f"{file_name}: topics 第 {index} 项必须是 JSON 对象，实际为 {type(entry).__name__}"
            )
        topic_id = _require_id(entry, file_name, "topic")
        if not ID_PATTERN.match(topic_id):
            raise ContentValidationError(f"{file_name}: topic id {topic_id!r} 不符合小写英文连字符格式")
        if topic_id in topics:
            raise ContentValidationError(f"{file_name}: topic id 重复：{topic_id!r}")
        stances = _require_str_tuple(entry, "stances", file_name, "topic", topic_id)
        if stances != REQUIRED_STANCES:
            raise ContentValidationError(
                f"{file_name}: topic {topic_id!r} 的 stances 必须恰好为 "
                f"{list(REQUIRED_STANCES)}，实际为 {list(stances)}"
            )
        topics[topic_id] = Topic(
            id=topic_id,
            title=_require_text(entry, "title", file_name, "topic", topic_id),
            question=_require_text(entry, "question", file_name, "topic", topic_id),
            tags=_require_str_tuple(entry, "tags", file_name, "topic", topic_id),
            stances=stances,
            opening_hint=_require_text(entry, "opening_hint", file_name, "topic", topic_id),
            memory_hook=_require_text(entry, "memory_hook", file_name, "topic", topic_id),
        )
    return topics


def _load_characters(document: dict[str, Any], file_name: str) -> dict[str, Character]:
    _require_version(document, file_name)
    characters: dict[str, Character] = {}
    for index, entry in enumerate(_require_entries(document, "characters", file_name)):
        if not isinstance(entry, dict):
            raise ContentValidationError(
                f"{file_name}: characters 第 {index} 项必须是 JSON 对象，实际为 {type(entry).__name__}"
            )
        character_id = _require_id(entry, file_name, "character")
        if character_id in characters:
            raise ContentValidationError(f"{file_name}: character id 重复：{character_id!r}")
        characters[character_id] = Character(
            id=character_id,
            name=_require_text(entry, "name", file_name, "character", character_id),
            role=_require_text(entry, "role", file_name, "character", character_id),
            voice=_require_text(entry, "voice", file_name, "character", character_id),
            game_function=_require_text(entry, "game_function", file_name, "character", character_id),
            must_do=_require_str_tuple(entry, "must_do", file_name, "character", character_id),
            must_not_do=_require_str_tuple(entry, "must_not_do", file_name, "character", character_id),
        )
    return characters


def _load_cards(
    document: dict[str, Any],
    file_name: str,
    topics: dict[str, Topic],
    characters: dict[str, Character],
) -> dict[str, RebuttalCard]:
    _require_version(document, file_name)
    cards: dict[str, RebuttalCard] = {}
    for index, entry in enumerate(_require_entries(document, "cards", file_name)):
        if not isinstance(entry, dict):
            raise ContentValidationError(
                f"{file_name}: cards 第 {index} 项必须是 JSON 对象，实际为 {type(entry).__name__}"
            )
        card_id = _require_id(entry, file_name, "card")
        if card_id in cards:
            raise ContentValidationError(f"{file_name}: card id 重复：{card_id!r}")

        topic_id = _require_text(entry, "topic_id", file_name, "card", card_id)
        if topic_id not in topics:
            raise ContentValidationError(f"{file_name}: card {card_id!r} 的 topic_id {topic_id!r} 未引用已定义的 topic")

        opponent_id = _require_text(entry, "opponent_id", file_name, "card", card_id)
        if opponent_id not in characters:
            raise ContentValidationError(
                f"{file_name}: card {card_id!r} 的 opponent_id {opponent_id!r} 未引用已定义的 character"
            )
        opponent_role = characters[opponent_id].role
        if opponent_role != "opponent":
            raise ContentValidationError(
                f"{file_name}: card {card_id!r} 的 opponent_id {opponent_id!r} "
                f"引用的 character role 为 {opponent_role!r}，必须为 'opponent'"
            )

        target_stance = _require_text(entry, "target_stance", file_name, "card", card_id)
        if target_stance not in REQUIRED_STANCES:
            raise ContentValidationError(
                f"{file_name}: card {card_id!r} 的 target_stance 非法：{target_stance!r}，"
                f"只能为 {list(REQUIRED_STANCES)}"
            )

        trigger_type = _require_text(entry, "trigger_type", file_name, "card", card_id)
        if trigger_type not in VALID_TRIGGER_TYPES:
            raise ContentValidationError(
                f"{file_name}: card {card_id!r} 的 trigger_type 非法：{trigger_type!r}，"
                f"只能为 {sorted(VALID_TRIGGER_TYPES)}"
            )

        if "weight" not in entry:
            raise ContentValidationError(f"{file_name}: card {card_id!r} 缺少必需字段 'weight'")
        weight = entry["weight"]
        if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
            raise ContentValidationError(f"{file_name}: card {card_id!r} 的 weight 必须是正整数，实际为 {weight!r}")

        if "memory_follow_up" not in entry:
            raise ContentValidationError(f"{file_name}: card {card_id!r} 缺少必需字段 'memory_follow_up'")
        memory_follow_up = entry["memory_follow_up"]
        if memory_follow_up is not None and not isinstance(memory_follow_up, str):
            raise ContentValidationError(
                f"{file_name}: card {card_id!r} 的 memory_follow_up 必须是字符串或 null，"
                f"实际为 {type(memory_follow_up).__name__}"
            )
        if isinstance(memory_follow_up, str) and not memory_follow_up.strip():
            raise ContentValidationError(f"{file_name}: card {card_id!r} 的 memory_follow_up 不能为空字符串")

        cards[card_id] = RebuttalCard(
            id=card_id,
            topic_id=topic_id,
            target_stance=target_stance,
            opponent_id=opponent_id,
            trigger_type=trigger_type,
            card_text=_require_text(entry, "card_text", file_name, "card", card_id),
            follow_up_question=_require_text(entry, "follow_up_question", file_name, "card", card_id),
            memory_follow_up=memory_follow_up,
            weight=weight,
        )

    _require_topic_coverage(cards, topics, file_name)
    return cards


def _require_topic_coverage(cards: dict[str, RebuttalCard], topics: dict[str, Topic], file_name: str) -> None:
    """每个辩题至少 6 张卡，两个立场各至少 3 张，且两名对手都要有卡。"""
    for topic_id in topics:
        topic_cards = [card for card in cards.values() if card.topic_id == topic_id]
        if len(topic_cards) < MIN_CARDS_PER_TOPIC:
            raise ContentValidationError(
                f"{file_name}: topic {topic_id!r} 的反击卡数量为 {len(topic_cards)}，"
                f"少于要求的 {MIN_CARDS_PER_TOPIC} 张"
            )
        for stance in REQUIRED_STANCES:
            count = sum(1 for card in topic_cards if card.target_stance == stance)
            if count < MIN_CARDS_PER_STANCE:
                raise ContentValidationError(
                    f"{file_name}: topic {topic_id!r} 反驳立场 {stance!r} 的反击卡数量为 {count}，"
                    f"少于要求的 {MIN_CARDS_PER_STANCE} 张"
                )
        for opponent_id in REQUIRED_OPPONENTS:
            if not any(card.opponent_id == opponent_id for card in topic_cards):
                raise ContentValidationError(f"{file_name}: topic {topic_id!r} 缺少对手 {opponent_id!r} 的反击卡")
