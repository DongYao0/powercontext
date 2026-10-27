"""节目内容目录与反击卡选择的行为测试。

只验证可观察行为，不依赖 dataclass 内部实现细节或调用次数。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from arena_service import (
    ContentCatalog,
    ContentValidationError,
    NoMatchingCardError,
    load_content_catalog,
    select_rebuttal_card,
)

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content-draft"
CONTENT_FILES = ("topics.json", "characters.json", "rebuttal_cards.draft.json")


class ContentCatalogLoadingTests(unittest.TestCase):
    """已验收内容资产的加载行为。"""

    def test_已验收内容资产可以成功加载(self) -> None:
        catalog = load_content_catalog(CONTENT_DIR)

        self.assertIsInstance(catalog, ContentCatalog)
        self.assertEqual(len(catalog.topics), 8)
        self.assertEqual(len(catalog.characters), 3)
        self.assertEqual(len(catalog.cards), 48)

    def test_目录内容不允许被外部改写(self) -> None:
        catalog = load_content_catalog(CONTENT_DIR)

        with self.assertRaises(TypeError):
            catalog.topics["injected"] = None  # type: ignore[index]
        with self.assertRaises(TypeError):
            catalog.cards["injected"] = None  # type: ignore[index]

    def test_按ID查询返回对应内容(self) -> None:
        catalog = load_content_catalog(CONTENT_DIR)

        self.assertEqual(catalog.topic("pearl-voting-rights").title, "珍珠是否应拥有投票权")
        self.assertEqual(catalog.character("logic-monster").name, "逻辑怪")
        self.assertEqual(catalog.character("host").role, "host")
        self.assertEqual(catalog.card("pearl-voting-rights-against-logic-01").trigger_type, "logic_gap")


class CardSelectionTests(unittest.TestCase):
    """确定性选卡行为。"""

    def setUp(self) -> None:
        self.catalog = load_content_catalog(CONTENT_DIR)

    def test_首次选择返回按ID排序的第一张且未复用(self) -> None:
        selection = select_rebuttal_card(
            self.catalog,
            topic_id="pearl-voting-rights",
            target_stance="反对",
            opponent_id="logic-monster",
            used_card_ids=(),
        )

        self.assertEqual(selection.card.id, "pearl-voting-rights-against-logic-01")
        self.assertFalse(selection.reused)

    def test_优先选择尚未使用过的卡(self) -> None:
        selection = select_rebuttal_card(
            self.catalog,
            topic_id="pearl-voting-rights",
            target_stance="反对",
            opponent_id="logic-monster",
            used_card_ids={"pearl-voting-rights-against-logic-01"},
        )

        self.assertEqual(selection.card.id, "pearl-voting-rights-against-logic-02")
        self.assertFalse(selection.reused)

    def test_候选全部使用过后返回第一张并标记为复用(self) -> None:
        candidates = self.catalog.cards_for(
            topic_id="pearl-voting-rights",
            target_stance="反对",
            opponent_id="logic-monster",
        )
        self.assertTrue(candidates)

        selection = select_rebuttal_card(
            self.catalog,
            topic_id="pearl-voting-rights",
            target_stance="反对",
            opponent_id="logic-monster",
            used_card_ids={card.id for card in candidates},
        )

        self.assertEqual(selection.card.id, "pearl-voting-rights-against-logic-01")
        self.assertTrue(selection.reused)

    def test_不存在的组合抛出NoMatchingCardError(self) -> None:
        with self.assertRaises(NoMatchingCardError):
            select_rebuttal_card(
                self.catalog,
                topic_id="no-such-topic",
                target_stance="反对",
                opponent_id="logic-monster",
                used_card_ids=(),
            )

        with self.assertRaises(NoMatchingCardError):
            select_rebuttal_card(
                self.catalog,
                topic_id="pearl-voting-rights",
                target_stance="反对",
                opponent_id="host",
                used_card_ids=(),
            )

    def test_相同输入始终得到相同结果(self) -> None:
        kwargs = {
            "topic_id": "pearl-voting-rights",
            "target_stance": "支持",
            "opponent_id": "logic-monster",
            "used_card_ids": (),
        }

        first = select_rebuttal_card(self.catalog, **kwargs)
        second = select_rebuttal_card(self.catalog, **kwargs)

        self.assertEqual(first.card.id, second.card.id)
        self.assertEqual(first.card.id, "pearl-voting-rights-support-logic-04")

    def test_选择过程不修改传入的已用集合与目录状态(self) -> None:
        used = {"pearl-voting-rights-against-logic-01"}
        cards_before = dict(self.catalog.cards)

        select_rebuttal_card(
            self.catalog,
            topic_id="pearl-voting-rights",
            target_stance="反对",
            opponent_id="logic-monster",
            used_card_ids=used,
        )

        self.assertEqual(used, {"pearl-voting-rights-against-logic-01"})
        self.assertEqual(dict(self.catalog.cards), cards_before)


class ContentValidationTests(unittest.TestCase):
    """内容资产不符合契约时的失败行为。"""

    def _copy_content(self, directory: Path) -> Path:
        target = directory / "content-draft"
        shutil.copytree(CONTENT_DIR, target)
        return target

    def test_篡改卡片的topic_id后加载失败并指出无效ID(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self._copy_content(Path(temporary))
            cards_path = target / "rebuttal_cards.draft.json"
            document = json.loads(cards_path.read_text(encoding="utf-8"))
            document["cards"][0]["topic_id"] = "not-a-real-topic"
            cards_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

            with self.assertRaises(ContentValidationError) as raised:
                load_content_catalog(target)

            message = str(raised.exception)
            self.assertIn("not-a-real-topic", message)
            self.assertIn("rebuttal_cards.draft.json", message)

    def test_缺少文件时加载失败并指出文件名(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self._copy_content(Path(temporary))
            (target / "characters.json").unlink()

            with self.assertRaises(ContentValidationError) as raised:
                load_content_catalog(target)

            message = str(raised.exception)
            self.assertIn("characters.json", message)

    def test_版本号不符时加载失败(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self._copy_content(Path(temporary))
            topics_path = target / "topics.json"
            document = json.loads(topics_path.read_text(encoding="utf-8"))
            document["version"] = "0.2"
            topics_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

            with self.assertRaises(ContentValidationError) as raised:
                load_content_catalog(target)

            message = str(raised.exception)
            self.assertIn("topics.json", message)
            self.assertIn("version", message)


class ContentIntegrityTests(unittest.TestCase):
    """加载与选择过程不得修改原始内容文件。"""

    def test_加载与选择不修改原始JSON内容(self) -> None:
        before = {name: (CONTENT_DIR / name).read_bytes() for name in CONTENT_FILES}

        catalog = load_content_catalog(CONTENT_DIR)
        select_rebuttal_card(
            catalog,
            topic_id="pearl-voting-rights",
            target_stance="反对",
            opponent_id="logic-monster",
            used_card_ids=(),
        )

        after = {name: (CONTENT_DIR / name).read_bytes() for name in CONTENT_FILES}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
