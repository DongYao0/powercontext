"""游戏记忆策略层的行为测试。

只用标准库 unittest；客户端是一个手写的记录器，不使用 mock、网络或真实 PowerContext。
"""

from __future__ import annotations

import dataclasses
import unittest

from arena_service import (
    ALLOWED_MEMORY_KINDS,
    MEMORY_TEXT_MAX_UTF8_BYTES,
    REASON_MAX_LENGTH,
    SCOPE_ID_MAX_LENGTH,
    SOURCE_ID_MAX_LENGTH,
    GameMemoryEvent,
    GameMemoryRecorder,
    GameMemoryValidationError,
)

SCOPE_ID = "scope-player-aqiang"
GAME_ID = "game-001"
TOPIC_ID = "pearl-voting-rights"
TOPIC_TITLE = "珍珠是否应拥有投票权"
PLAYER_MESSAGE = "珍珠没有手，所以不应该拥有投票权。"


class RecordingClient:
    """记录每次 record_memory 调用参数的手写客户端。"""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._error = error

    def record_memory(
        self,
        *,
        scope_id: str,
        source_id: str,
        source_content: str,
        metadata: dict,
        memory_kind: str,
        memory_text: str,
        reason: str,
    ) -> None:
        self.calls.append({
            "scope_id": scope_id,
            "source_id": source_id,
            "source_content": source_content,
            "metadata": metadata,
            "memory_kind": memory_kind,
            "memory_text": memory_text,
            "reason": reason,
        })
        if self._error is not None:
            raise self._error


def make_event(**overrides: object) -> GameMemoryEvent:
    """构造一个合法的记忆事件，字段可覆盖。"""
    values = {
        "game_id": GAME_ID,
        "round_number": 2,
        "player_nickname": "阿强",
        "topic_id": TOPIC_ID,
        "topic_title": TOPIC_TITLE,
        "final_stance": "反对",
        "player_message": PLAYER_MESSAGE,
        "memory_kind": "stance",
        "memory_text": "阿强在珍珠是否应拥有投票权一局选择反对。",
        "reason": "与游戏直接相关的立场记录。",
    }
    values.update(overrides)
    return GameMemoryEvent(**values)


class RecorderCallTests(unittest.TestCase):
    """合法事件会怎样调用客户端。"""

    def setUp(self) -> None:
        self.client = RecordingClient()
        self.recorder = GameMemoryRecorder(self.client)

    def test_合法事件恰好调用一次(self) -> None:
        self.recorder.record(scope_id=SCOPE_ID, event=make_event())

        self.assertEqual(len(self.client.calls), 1)

    def test_调用参数与约定完全一致(self) -> None:
        self.recorder.record(scope_id=SCOPE_ID, event=make_event())

        call = self.client.calls[0]
        self.assertEqual(call["scope_id"], SCOPE_ID)
        self.assertEqual(call["source_id"], "ai-debate-show:game-001:round:2:memory:stance")
        self.assertEqual(
            call["source_content"],
            "玩家昵称：阿强\n"
            "辩题：珍珠是否应拥有投票权（pearl-voting-rights）\n"
            "回合：2\n"
            "本局结束立场：反对\n"
            "玩家发言：珍珠没有手，所以不应该拥有投票权。\n"
            "记忆候选（stance）：阿强在珍珠是否应拥有投票权一局选择反对。\n"
            "写入理由：与游戏直接相关的立场记录。",
        )
        self.assertEqual(
            call["metadata"],
            {
                "application": "ai-debate-show",
                "game_id": "game-001",
                "round_number": 2,
                "topic_id": "pearl-voting-rights",
                "memory_kind": "stance",
            },
        )
        self.assertEqual(call["memory_kind"], "stance")
        self.assertEqual(call["memory_text"], "阿强在珍珠是否应拥有投票权一局选择反对。")
        self.assertEqual(call["reason"], "与游戏直接相关的立场记录。")

    def test_相同事件重复构造得到相同来源标识(self) -> None:
        self.recorder.record(scope_id=SCOPE_ID, event=make_event())
        self.recorder.record(scope_id=SCOPE_ID, event=make_event())

        first = self.client.calls[0]["source_id"]
        second = self.client.calls[1]["source_id"]
        self.assertEqual(first, second)
        self.assertEqual(first, "ai-debate-show:game-001:round:2:memory:stance")

    def test_六种合法记忆类型都可写入(self) -> None:
        kinds = ("stance", "quote", "persona", "promise", "reversal", "catchphrase")
        self.assertEqual(set(kinds), set(ALLOWED_MEMORY_KINDS))

        for kind in kinds:
            with self.subTest(memory_kind=kind):
                self.client.calls.clear()
                self.recorder.record(scope_id=SCOPE_ID, event=make_event(memory_kind=kind))

                self.assertEqual(len(self.client.calls), 1)
                self.assertEqual(self.client.calls[0]["memory_kind"], kind)
                self.assertTrue(self.client.calls[0]["source_id"].endswith(f":memory:{kind}"))

    def test_元数据不包含昵称原话或Scope(self) -> None:
        self.recorder.record(scope_id=SCOPE_ID, event=make_event())

        metadata = self.client.calls[0]["metadata"]
        self.assertNotIn("阿强", str(metadata))
        self.assertNotIn(PLAYER_MESSAGE, str(metadata))
        self.assertNotIn(SCOPE_ID, str(metadata))
        self.assertEqual(
            set(metadata),
            {"application", "game_id", "round_number", "topic_id", "memory_kind"},
        )


class RecorderValidationTests(unittest.TestCase):
    """非法事件必须在零调用的情况下失败。"""

    def setUp(self) -> None:
        self.client = RecordingClient()
        self.recorder = GameMemoryRecorder(self.client)

    def _assert_rejected(self, event: GameMemoryEvent) -> None:
        with self.assertRaises(GameMemoryValidationError):
            self.recorder.record(scope_id=SCOPE_ID, event=event)
        self.assertEqual(self.client.calls, [])

    def test_非法记忆类型被拒绝(self) -> None:
        self._assert_rejected(make_event(memory_kind="chitchat"))

    def test_非法回合序号被拒绝(self) -> None:
        for value in (0, 4):
            with self.subTest(round_number=value):
                self._assert_rejected(make_event(round_number=value))

    def test_布尔或非整数回合序号被拒绝(self) -> None:
        for value in (True, 1.5, "2", None):
            with self.subTest(round_number=value):
                with self.assertRaises((TypeError, GameMemoryValidationError)):
                    self.recorder.record(scope_id=SCOPE_ID, event=make_event(round_number=value))
                self.assertEqual(self.client.calls, [])

    def test_非法立场被拒绝(self) -> None:
        for value in ("中立", "支持反对", ""):
            with self.subTest(final_stance=value):
                self._assert_rejected(make_event(final_stance=value))

    def test_空白与空串文本字段被拒绝(self) -> None:
        blank_fields = (
            "game_id",
            "player_nickname",
            "topic_id",
            "topic_title",
            "player_message",
            "memory_text",
            "reason",
        )
        for field in blank_fields:
            for value in ("", "   "):
                with self.subTest(field=field, value=value):
                    self._assert_rejected(make_event(**{field: value}))

    def test_空白scope_id被拒绝(self) -> None:
        for value in ("", "   "):
            with self.subTest(scope_id=value):
                with self.assertRaises(GameMemoryValidationError):
                    self.recorder.record(scope_id=value, event=make_event())
                self.assertEqual(self.client.calls, [])


class MemoryTextLengthTests(unittest.TestCase):
    """8192 UTF-8 字节上限：拒绝而不截断。"""

    def setUp(self) -> None:
        self.client = RecordingClient()
        self.recorder = GameMemoryRecorder(self.client)

    def test_恰好8192字节的ASCII正文可以写入(self) -> None:
        text = "a" * MEMORY_TEXT_MAX_UTF8_BYTES
        self.assertEqual(len(text.encode("utf-8")), 8192)

        self.recorder.record(scope_id=SCOPE_ID, event=make_event(memory_text=text))

        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.client.calls[0]["memory_text"], text)

    def test_8193字节的ASCII正文被拒绝(self) -> None:
        text = "a" * (MEMORY_TEXT_MAX_UTF8_BYTES + 1)

        with self.assertRaises(GameMemoryValidationError):
            self.recorder.record(scope_id=SCOPE_ID, event=make_event(memory_text=text))

        self.assertEqual(self.client.calls, [])

    def test_多字节中文超限同样被拒绝(self) -> None:
        text = "你" * 2731
        self.assertEqual(len(text.encode("utf-8")), 8193)

        with self.assertRaises(GameMemoryValidationError):
            self.recorder.record(scope_id=SCOPE_ID, event=make_event(memory_text=text))

        self.assertEqual(self.client.calls, [])

    def test_超限错误信息指出长度且不截断(self) -> None:
        text = "a" * 9000

        with self.assertRaises(GameMemoryValidationError) as raised:
            self.recorder.record(scope_id=SCOPE_ID, event=make_event(memory_text=text))

        message = str(raised.exception)
        self.assertIn("9000", message)
        self.assertIn("8192", message)
        self.assertEqual(self.client.calls, [])


class ClientErrorPropagationTests(unittest.TestCase):
    """客户端异常必须原样上抛。"""

    def test_不吞掉客户端抛出的异常(self) -> None:
        boom = RuntimeError("写入失败")
        client = RecordingClient(error=boom)
        recorder = GameMemoryRecorder(client)

        with self.assertRaises(RuntimeError) as raised:
            recorder.record(scope_id=SCOPE_ID, event=make_event())

        self.assertIs(raised.exception, boom)
        self.assertEqual(len(client.calls), 1)


class ServiceLengthPrecheckTests(unittest.TestCase):
    """按服务端契约做的写入前长度与字符集预检。"""

    def setUp(self) -> None:
        self.client = RecordingClient()
        self.recorder = GameMemoryRecorder(self.client)

    def test_256字符的scope_id可以写入(self) -> None:
        scope_id = "s" * SCOPE_ID_MAX_LENGTH

        self.recorder.record(scope_id=scope_id, event=make_event())

        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.client.calls[0]["scope_id"], scope_id)

    def test_257字符的scope_id被拒绝且零调用(self) -> None:
        scope_id = "s" * (SCOPE_ID_MAX_LENGTH + 1)

        with self.assertRaises(GameMemoryValidationError):
            self.recorder.record(scope_id=scope_id, event=make_event())

        self.assertEqual(self.client.calls, [])

    def test_512字符的reason可以写入(self) -> None:
        reason = "理" * REASON_MAX_LENGTH

        self.recorder.record(scope_id=SCOPE_ID, event=make_event(reason=reason))

        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.client.calls[0]["reason"], reason)

    def test_513字符的reason被拒绝且零调用(self) -> None:
        reason = "理" * (REASON_MAX_LENGTH + 1)

        with self.assertRaises(GameMemoryValidationError):
            self.recorder.record(scope_id=SCOPE_ID, event=make_event(reason=reason))

        self.assertEqual(self.client.calls, [])

    def test_恰好容纳的game_id生成256字符source_id并写入(self) -> None:
        fixed = len("ai-debate-show:") + len(":round:2:memory:stance")
        game_id = "g" * (SOURCE_ID_MAX_LENGTH - fixed)

        self.recorder.record(scope_id=SCOPE_ID, event=make_event(game_id=game_id))

        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(len(self.client.calls[0]["source_id"]), SOURCE_ID_MAX_LENGTH)

    def test_多一个字符的game_id被拒绝且零调用(self) -> None:
        fixed = len("ai-debate-show:") + len(":round:2:memory:stance")
        game_id = "g" * (SOURCE_ID_MAX_LENGTH - fixed + 1)

        with self.assertRaises(GameMemoryValidationError):
            self.recorder.record(scope_id=SCOPE_ID, event=make_event(game_id=game_id))

        self.assertEqual(self.client.calls, [])

    def test_含中文空格或换行的game_id分别被拒绝(self) -> None:
        for game_id in ("game-001中", "game 001", "game\n001", "game\t001"):
            with self.subTest(game_id=game_id):
                with self.assertRaises(GameMemoryValidationError):
                    self.recorder.record(scope_id=SCOPE_ID, event=make_event(game_id=game_id))
                self.assertEqual(self.client.calls, [])

    def test_新常量可从包导入且取值正确(self) -> None:
        from arena_service import (  # noqa: F401
            REASON_MAX_LENGTH as reason_limit,
        )

        self.assertEqual(SCOPE_ID_MAX_LENGTH, 256)
        self.assertEqual(SOURCE_ID_MAX_LENGTH, 256)
        self.assertEqual(REASON_MAX_LENGTH, 512)


class PublicApiTests(unittest.TestCase):
    """公开 API 的形状。"""

    def test_记忆事件是冻结dataclass(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(GameMemoryEvent))
        self.assertTrue(GameMemoryEvent.__dataclass_params__.frozen)

        event = make_event()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.game_id = "other"

    def test_常量与约定一致(self) -> None:
        self.assertEqual(MEMORY_TEXT_MAX_UTF8_BYTES, 8192)
        self.assertEqual(
            ALLOWED_MEMORY_KINDS,
            frozenset({"stance", "quote", "persona", "promise", "reversal", "catchphrase"}),
        )

    def test_从包导入新增公共符号成功(self) -> None:
        from arena_service import (  # noqa: F401
            ALLOWED_MEMORY_KINDS as kinds,
        )
        from arena_service import (
            GameMemoryRecorder as recorder_cls,
        )
        from arena_service import (
            GameMemoryValidationError as error_cls,
        )

        self.assertTrue(callable(recorder_cls))
        self.assertTrue(issubclass(error_cls, ValueError))


if __name__ == "__main__":
    unittest.main()
