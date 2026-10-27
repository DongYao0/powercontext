"""Arena 应用层的行为测试。

不访问外网，不启动真实 PowerContext：记忆能力用手写桩客户端替代。
"""

from __future__ import annotations

import threading
import unittest
from pathlib import Path

from arena_service import (
    ArenaApplication,
    ArenaApplicationError,
    ArenaSession,
    GameNotFoundError,
    MemoryUnavailableError,
    load_content_catalog,
)
from arena_service.powercontext import PowerContextError, PowerContextWriteError

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content-draft"
TOPIC_ID = "pearl-voting-rights"
OPPONENT_ID = "logic-monster"
GAME_ID = "game-app-001"
SCOPE_ID = "trusted-scope-id"
NICKNAME = "阿强"


class StubMemoryClient:
    """手写的记忆客户端桩：可返回历史、可抛异常。"""

    def __init__(
        self,
        *,
        content: str | None = "上回阿强说珍珠没有手，所以不应该拥有投票权。",
        status: str = "ready",
        prepare_error: Exception | None = None,
        write_error: Exception | None = None,
    ) -> None:
        self.content = content
        self.status = status
        self.prepare_error = prepare_error
        self.write_error = write_error
        self.prepare_calls: list[dict] = []
        self.record_calls: list[dict] = []

    def prepare_context(self, *, scope_id: str, query: str, max_bytes: int):
        self.prepare_calls.append({"scope_id": scope_id, "query": query, "max_bytes": max_bytes})
        if self.prepare_error is not None:
            raise self.prepare_error
        from arena_service.powercontext import PreparedContext

        return PreparedContext(status=self.status, content=self.content)

    def record_memory(self, **kwargs) -> None:
        self.record_calls.append(kwargs)
        if self.write_error is not None:
            raise self.write_error


def new_application(client=None) -> ArenaApplication:
    return ArenaApplication(load_content_catalog(CONTENT_DIR), client)


def create_game(app: ArenaApplication, game_id: str = GAME_ID) -> ArenaSession:
    return app.start_game(
        game_id=game_id,
        scope_id=SCOPE_ID,
        player_nickname=NICKNAME,
        topic_id=TOPIC_ID,
        initial_stance="反对",
        opponent_id=OPPONENT_ID,
    )


class StartGameTests(unittest.TestCase):
    """开局行为。"""

    def test_有历史时返回ready与上下文(self) -> None:
        client = StubMemoryClient(content="上回阿强站在反对立场。")
        app = new_application(client)

        session = create_game(app)

        self.assertEqual(session.memory_status, "ready")
        self.assertEqual(session.memory_context, "上回阿强站在反对立场。")
        self.assertEqual(session.scope_id, SCOPE_ID)
        self.assertEqual(session.state.completed_rounds, 0)
        self.assertEqual(session.state.used_card_ids, ())
        self.assertFalse(session.state.finished)
        self.assertEqual(session.topic_title, "珍珠是否应拥有投票权")

    def test_准备历史的查询串符合约定(self) -> None:
        client = StubMemoryClient()
        app = new_application(client)

        create_game(app)

        self.assertEqual(
            client.prepare_calls[0],
            {
                "scope_id": SCOPE_ID,
                "query": "辩题：珍珠是否应拥有投票权；当前立场：反对；玩家：阿强",
                "max_bytes": 4000,
            },
        )

    def test_无历史时降级但游戏仍创建成功(self) -> None:
        app = new_application(StubMemoryClient(status="empty", content=None))

        session = create_game(app)

        self.assertEqual(session.memory_status, "degraded")
        self.assertIsNone(session.memory_context)
        self.assertEqual(session.state.game_id, GAME_ID)

    def test_记忆服务异常时游戏仍创建成功且降级(self) -> None:
        client = StubMemoryClient(prepare_error=PowerContextError("连接失败"))
        app = new_application(client)

        session = create_game(app)

        self.assertEqual(session.memory_status, "degraded")
        self.assertIsNone(session.memory_context)
        self.assertEqual(session.state.game_id, GAME_ID)

    def test_未配置记忆客户端时降级(self) -> None:
        app = new_application(None)

        session = create_game(app)

        self.assertEqual(session.memory_status, "degraded")
        self.assertIsNone(session.memory_context)
        self.assertFalse(app.powercontext_configured)

    def test_重复game_id被拒绝(self) -> None:
        app = new_application(StubMemoryClient())
        create_game(app)

        with self.assertRaises(ArenaApplicationError):
            create_game(app)

    def test_不同game_id可以并存(self) -> None:
        app = new_application(StubMemoryClient())

        create_game(app, "game-a")
        create_game(app, "game-b")

    def test_非法参数被拒绝(self) -> None:
        app = new_application(StubMemoryClient())

        with self.assertRaises(ValueError):
            app.start_game(
                game_id=GAME_ID,
                scope_id="",
                player_nickname=NICKNAME,
                topic_id=TOPIC_ID,
                initial_stance="反对",
                opponent_id=OPPONENT_ID,
            )


class PlayRoundTests(unittest.TestCase):
    """回合推进。"""

    def setUp(self) -> None:
        self.app = new_application(StubMemoryClient())
        self.session = create_game(self.app)

    def test_三回合推进(self) -> None:
        plan = self.app.play_round(
            game_id=GAME_ID,
            player_action="double_down",
            player_message="珍珠没有手。",
        )

        self.assertEqual(plan.round_number, 1)
        self.assertFalse(plan.game_finished)
        self.assertEqual(plan.state.completed_rounds, 1)
        self.assertTrue(plan.opponent_message)
        self.assertTrue(plan.follow_up_question)

    def test_不存在game_id被拒绝(self) -> None:
        with self.assertRaises(GameNotFoundError):
            self.app.play_round(
                game_id="no-such-game",
                player_action="double_down",
                player_message="珍珠没有手。",
            )

    def test_游戏结束后不能继续推进(self) -> None:
        state = self.session.state
        for index in range(3):
            plan = self.app.play_round(
                game_id=GAME_ID,
                player_action="double_down",
                player_message=f"第{index + 1}次嘴硬",
            )
            state = plan.state

        self.assertTrue(state.finished)
        with self.assertRaises(ArenaApplicationError):
            self.app.play_round(
                game_id=GAME_ID,
                player_action="double_down",
                player_message="还想说",
            )

    def test_并发推进不同对局互不串扰(self) -> None:
        app = new_application(StubMemoryClient())
        create_game(app, "game-x")
        create_game(app, "game-y")
        errors: list[Exception] = []
        results: dict[str, list] = {}

        def run(game_id: str) -> None:
            try:
                plans = []
                for index in range(3):
                    plans.append(
                        app.play_round(
                            game_id=game_id,
                            player_action="double_down",
                            player_message=f"{game_id} 第{index + 1}回合",
                        )
                    )
                results[game_id] = plans
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=run, args=("game-x",)),
            threading.Thread(target=run, args=("game-y",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        for game_id in ("game-x", "game-y"):
            plans = results[game_id]
            self.assertEqual([plan.round_number for plan in plans], [1, 2, 3])
            self.assertEqual(plans[-1].state.completed_rounds, 3)
            self.assertTrue(plans[-1].game_finished)
            self.assertEqual(plans[-1].state.game_id, game_id)
        self.assertEqual(
            results["game-x"][-1].state.used_card_ids,
            results["game-y"][-1].state.used_card_ids,
        )


class RecordFinalMemoryTests(unittest.TestCase):
    """结算记忆写入。"""

    def _finish_game(self, app: ArenaApplication) -> None:
        for index in range(3):
            app.play_round(
                game_id=GAME_ID,
                player_action="double_down",
                player_message=f"第{index + 1}回合发言",
            )

    def test_未结束的游戏不能写入记忆(self) -> None:
        app = new_application(StubMemoryClient())
        create_game(app)

        with self.assertRaises(ArenaApplicationError):
            app.record_final_memory(
                game_id=GAME_ID,
                player_message="还没说完",
                memory_kind="stance",
                memory_text="记忆正文",
                reason="理由",
            )

    def test_结束后写入一次成功(self) -> None:
        client = StubMemoryClient()
        app = new_application(client)
        create_game(app)
        self._finish_game(app)

        app.record_final_memory(
            game_id=GAME_ID,
            player_message="最后一回合发言",
            memory_kind="stance",
            memory_text="阿强在珍珠投票权一局选择反对。",
            reason="与游戏直接相关的立场记录。",
        )

        self.assertEqual(len(client.record_calls), 1)
        call = client.record_calls[0]
        self.assertEqual(call["scope_id"], SCOPE_ID)
        self.assertEqual(call["memory_kind"], "stance")
        self.assertEqual(call["memory_text"], "阿强在珍珠投票权一局选择反对。")
        self.assertEqual(call["source_id"], f"ai-debate-show:{GAME_ID}:round:3:memory:stance")

    def test_同种memory_kind重复写入被拒绝(self) -> None:
        client = StubMemoryClient()
        app = new_application(client)
        create_game(app)
        self._finish_game(app)

        app.record_final_memory(
            game_id=GAME_ID,
            player_message="最后一回合发言",
            memory_kind="stance",
            memory_text="阿强在珍珠投票权一局选择反对。",
            reason="理由",
        )
        with self.assertRaises(ArenaApplicationError):
            app.record_final_memory(
                game_id=GAME_ID,
                player_message="最后一回合发言",
                memory_kind="stance",
                memory_text="再来一次",
                reason="理由",
            )

        self.assertEqual(len(client.record_calls), 1)

    def test_不同memory_kind可以各写一次(self) -> None:
        client = StubMemoryClient()
        app = new_application(client)
        create_game(app)
        self._finish_game(app)

        for kind in ("stance", "quote"):
            app.record_final_memory(
                game_id=GAME_ID,
                player_message="最后一回合发言",
                memory_kind=kind,
                memory_text=f"{kind} 正文",
                reason="理由",
            )

        self.assertEqual(len(client.record_calls), 2)

    def test_未配置记忆客户端时抛MemoryUnavailableError(self) -> None:
        app = new_application(None)
        create_game(app)
        self._finish_game(app)

        with self.assertRaises(MemoryUnavailableError):
            app.record_final_memory(
                game_id=GAME_ID,
                player_message="最后一回合发言",
                memory_kind="stance",
                memory_text="记忆正文",
                reason="理由",
            )

    def test_部分成功状态被保留(self) -> None:
        failure = PowerContextWriteError("记忆写入失败", source_recorded=True)
        client = StubMemoryClient(write_error=failure)
        app = new_application(client)
        create_game(app)
        self._finish_game(app)

        with self.assertRaises(PowerContextWriteError) as raised:
            app.record_final_memory(
                game_id=GAME_ID,
                player_message="最后一回合发言",
                memory_kind="stance",
                memory_text="记忆正文",
                reason="理由",
            )

        self.assertTrue(raised.exception.source_recorded)

    def test_写入失败后允许重试(self) -> None:
        client = StubMemoryClient(write_error=PowerContextWriteError("记忆写入失败", source_recorded=False))
        app = new_application(client)
        create_game(app)
        self._finish_game(app)

        with self.assertRaises(PowerContextWriteError):
            app.record_final_memory(
                game_id=GAME_ID,
                player_message="最后一回合发言",
                memory_kind="stance",
                memory_text="记忆正文",
                reason="理由",
            )

        client.write_error = None
        app.record_final_memory(
            game_id=GAME_ID,
            player_message="最后一回合发言",
            memory_kind="stance",
            memory_text="记忆正文",
            reason="理由",
        )
        self.assertEqual(len(client.record_calls), 2)

    def test_不存在game_id写入被拒绝(self) -> None:
        app = new_application(StubMemoryClient())

        with self.assertRaises(GameNotFoundError):
            app.record_final_memory(
                game_id="no-such-game",
                player_message="发言",
                memory_kind="stance",
                memory_text="记忆正文",
                reason="理由",
            )


if __name__ == "__main__":
    unittest.main()
