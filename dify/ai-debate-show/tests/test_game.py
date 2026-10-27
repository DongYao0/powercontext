"""三回合对局状态机的行为测试。

只使用标准库 unittest，直接加载仓库里已验收的 content-draft 真实资产，
不复制也不修改任何 JSON。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from arena_service import (
    GAME_ACTIONS,
    GameFinishedError,
    GameInputError,
    GameState,
    RoundPlan,
    advance_round,
    load_content_catalog,
    start_game,
)

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content-draft"
TOPIC_ID = "pearl-voting-rights"
OPPONENT_ID = "logic-monster"
GAME_ID = "game-007"
NICKNAME = "阿强"


class GameTestCase(unittest.TestCase):
    """共用的内容目录与开局。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_content_catalog(CONTENT_DIR)

    def new_game(self, stance: str = "反对") -> GameState:
        return start_game(
            self.catalog,
            game_id=GAME_ID,
            player_nickname=NICKNAME,
            topic_id=TOPIC_ID,
            initial_stance=stance,
            opponent_id=OPPONENT_ID,
        )

    def play(
        self,
        state: GameState,
        action: str = "double_down",
        message: str = "珍珠没有手，所以不应该拥有投票权。",
    ) -> RoundPlan:
        return advance_round(
            self.catalog,
            state=state,
            player_action=action,
            player_message=message,
        )


class StartGameTests(GameTestCase):
    """开局行为。"""

    def test_正常开局得到初始状态(self) -> None:
        state = self.new_game()

        self.assertEqual(state.game_id, GAME_ID)
        self.assertEqual(state.player_nickname, NICKNAME)
        self.assertEqual(state.topic_id, TOPIC_ID)
        self.assertEqual(state.opponent_id, OPPONENT_ID)
        self.assertEqual(state.current_stance, "反对")
        self.assertEqual(state.completed_rounds, 0)
        self.assertEqual(state.used_card_ids, ())
        self.assertFalse(state.finished)

    def test_初始立场可以是支持(self) -> None:
        state = self.new_game(stance="支持")

        self.assertEqual(state.current_stance, "支持")

    def test_不存在的辩题被拒绝(self) -> None:
        with self.assertRaises(GameInputError) as raised:
            start_game(
                self.catalog,
                game_id=GAME_ID,
                player_nickname=NICKNAME,
                topic_id="no-such-topic",
                initial_stance="反对",
                opponent_id=OPPONENT_ID,
            )

        self.assertIn("topic_id", str(raised.exception))

    def test_非对手角色被拒绝(self) -> None:
        with self.assertRaises(GameInputError) as raised:
            start_game(
                self.catalog,
                game_id=GAME_ID,
                player_nickname=NICKNAME,
                topic_id=TOPIC_ID,
                initial_stance="反对",
                opponent_id="host",
            )

        self.assertIn("opponent_id", str(raised.exception))

    def test_不存在的对手被拒绝(self) -> None:
        with self.assertRaises(GameInputError) as raised:
            start_game(
                self.catalog,
                game_id=GAME_ID,
                player_nickname=NICKNAME,
                topic_id=TOPIC_ID,
                initial_stance="反对",
                opponent_id="no-such-opponent",
            )

        self.assertIn("opponent_id", str(raised.exception))

    def test_非法立场被拒绝(self) -> None:
        for stance in ("中立", "", "  "):
            with self.subTest(initial_stance=stance):
                with self.assertRaises(GameInputError) as raised:
                    start_game(
                        self.catalog,
                        game_id=GAME_ID,
                        player_nickname=NICKNAME,
                        topic_id=TOPIC_ID,
                        initial_stance=stance,
                        opponent_id=OPPONENT_ID,
                    )
                self.assertIn("initial_stance", str(raised.exception))

    def test_空标识与空昵称被拒绝(self) -> None:
        for field, kwargs in (
            ("game_id", {"game_id": "  "}),
            ("player_nickname", {"player_nickname": ""}),
        ):
            with self.subTest(field=field):
                base = {
                    "game_id": GAME_ID,
                    "player_nickname": NICKNAME,
                    "topic_id": TOPIC_ID,
                    "initial_stance": "反对",
                    "opponent_id": OPPONENT_ID,
                }
                base.update(kwargs)
                with self.assertRaises(GameInputError) as raised:
                    start_game(self.catalog, **base)
                self.assertIn(field, str(raised.exception))

    def test_开局不修改内容目录(self) -> None:
        before = {
            "topics": dict(self.catalog.topics),
            "characters": dict(self.catalog.characters),
            "cards": dict(self.catalog.cards),
        }

        self.new_game()

        self.assertEqual(dict(self.catalog.topics), before["topics"])
        self.assertEqual(dict(self.catalog.characters), before["characters"])
        self.assertEqual(dict(self.catalog.cards), before["cards"])


class AdvanceRoundTests(GameTestCase):
    """回合推进行为。"""

    def test_四种动作都可以推进(self) -> None:
        self.assertEqual(GAME_ACTIONS, ("double_down", "switch_explain", "wild_card", "free_input"))
        for action in GAME_ACTIONS:
            with self.subTest(player_action=action):
                state = self.new_game()
                plan = self.play(state, action=action)

                self.assertEqual(plan.round_number, 1)
                self.assertEqual(plan.player_action, action)
                self.assertEqual(plan.state.completed_rounds, 1)

    def test_非法动作被拒绝(self) -> None:
        state = self.new_game()

        for action in ("talking", "", None):
            with self.subTest(player_action=action):
                with self.assertRaises(GameInputError) as raised:
                    self.play(state, action=action)
                self.assertIn("player_action", str(raised.exception))

    def test_空发言被拒绝(self) -> None:
        state = self.new_game()

        with self.assertRaises(GameInputError) as raised:
            self.play(state, message="   ")

        self.assertIn("player_message", str(raised.exception))

    def test_改口动作翻转立场两次后回到原值(self) -> None:
        state = self.new_game(stance="反对")

        first = self.play(state, action="switch_explain")
        self.assertEqual(first.state.current_stance, "支持")

        second = self.play(first.state, action="switch_explain")
        self.assertEqual(second.state.current_stance, "反对")

    def test_其余动作保持立场不变(self) -> None:
        for action in ("double_down", "wild_card", "free_input"):
            with self.subTest(player_action=action):
                state = self.new_game(stance="反对")
                plan = self.play(state, action=action)

                self.assertEqual(plan.state.current_stance, "反对")

    def test_回合编号依次为123(self) -> None:
        state = self.new_game()

        first = self.play(state)
        self.assertEqual(first.round_number, 1)

        second = self.play(first.state)
        self.assertEqual(second.round_number, 2)

        third = self.play(second.state)
        self.assertEqual(third.round_number, 3)

    def test_三回合后恰好结算(self) -> None:
        state = self.new_game()

        first = self.play(state)
        self.assertFalse(first.state.finished)
        self.assertFalse(first.game_finished)

        second = self.play(first.state)
        self.assertFalse(second.state.finished)
        self.assertFalse(second.game_finished)

        third = self.play(second.state)
        self.assertTrue(third.state.finished)
        self.assertTrue(third.game_finished)
        self.assertEqual(third.state.completed_rounds, 3)

    def test_结算后再次推进抛GameFinishedError(self) -> None:
        state = self.new_game()
        first = self.play(state)
        second = self.play(first.state)
        third = self.play(second.state)

        with self.assertRaises(GameFinishedError):
            self.play(third.state)

    def test_已用卡ID逐回合累计(self) -> None:
        state = self.new_game()

        first = self.play(state)
        self.assertEqual(first.state.used_card_ids, (first.selected_card_id,))

        second = self.play(first.state)
        self.assertEqual(
            second.state.used_card_ids,
            first.state.used_card_ids + (second.selected_card_id,),
        )

        third = self.play(second.state)
        self.assertEqual(
            third.state.used_card_ids,
            second.state.used_card_ids + (third.selected_card_id,),
        )

    def test_第三回合触发复用卡路径(self) -> None:
        state = self.new_game()

        first = self.play(state)
        self.assertFalse(first.card_reused)

        second = self.play(first.state)
        self.assertFalse(second.card_reused)

        third = self.play(second.state)
        self.assertTrue(third.card_reused)
        self.assertEqual(third.selected_card_id, first.selected_card_id)

    def test_原状态不被修改(self) -> None:
        state = self.new_game()
        snapshot = (
            state.game_id,
            state.player_nickname,
            state.topic_id,
            state.opponent_id,
            state.current_stance,
            state.completed_rounds,
            state.used_card_ids,
            state.finished,
        )

        plan = self.play(state)

        self.assertNotEqual(plan.state, state)
        self.assertEqual(
            (
                state.game_id,
                state.player_nickname,
                state.topic_id,
                state.opponent_id,
                state.current_stance,
                state.completed_rounds,
                state.used_card_ids,
                state.finished,
            ),
            snapshot,
        )

    def test_对手消息与追问和卡片内容一致(self) -> None:
        state = self.new_game()

        plan = self.play(state)
        card = self.catalog.card(plan.selected_card_id)

        self.assertEqual(plan.opponent_message, card.card_text)
        self.assertEqual(plan.follow_up_question, card.follow_up_question)

    def test_选中卡片的立场与对手和本局一致(self) -> None:
        state = self.new_game()

        plan = self.play(state)
        card = self.catalog.card(plan.selected_card_id)

        self.assertEqual(card.topic_id, state.topic_id)
        self.assertEqual(card.opponent_id, state.opponent_id)
        self.assertEqual(card.target_stance, plan.state.current_stance)

    def test_改口后改用新立场的卡(self) -> None:
        state = self.new_game(stance="反对")

        plan = self.play(state, action="switch_explain")
        card = self.catalog.card(plan.selected_card_id)

        self.assertEqual(plan.state.current_stance, "支持")
        self.assertEqual(card.target_stance, "支持")


class PublicApiTests(unittest.TestCase):
    """公开 API 的形状。"""

    def test_从包导入全部新增公开API(self) -> None:
        from arena_service import (
            GAME_ACTIONS as actions,
        )
        from arena_service import (
            GameFinishedError as finished_error,
        )
        from arena_service import (
            GameInputError as input_error,
        )
        from arena_service import (
            advance_round as advance,
        )
        from arena_service import (
            start_game as start,
        )

        self.assertEqual(actions, ("double_down", "switch_explain", "wild_card", "free_input"))
        self.assertTrue(callable(start))
        self.assertTrue(callable(advance))
        self.assertTrue(issubclass(input_error, ValueError))
        self.assertTrue(issubclass(finished_error, RuntimeError))

    def test_状态与计划是冻结dataclass(self) -> None:
        import dataclasses

        self.assertTrue(dataclasses.is_dataclass(GameState))
        self.assertTrue(dataclasses.is_dataclass(RoundPlan))
        self.assertTrue(GameState.__dataclass_params__.frozen)
        self.assertTrue(RoundPlan.__dataclass_params__.frozen)


if __name__ == "__main__":
    unittest.main()
