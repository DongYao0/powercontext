"""PowerContext HTTP 客户端的行为测试。

测试只启动监听本机回环地址的临时 HTTP Server，不访问真实 PowerContext，
也不访问项目目录以外的任何服务。
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from arena_service import (
    PowerContextClient,
    PowerContextError,
    PowerContextWriteError,
    PreparedContext,
)

TEST_TOKEN = "stub-token-9f3a2b7c-do-not-leak"
PREPARE_PATH = "/v1/context/prepare"
SOURCE_PATH = "/v1/sources/content"
REMEMBER_PATH = "/v1/memory/remember"


class _StubHandler(BaseHTTPRequestHandler):
    """记录请求并按预设顺序返回响应的处理器。"""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        stub = self.server.stub  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        raw_body = self.rfile.read(length)
        stub.requests.append({
            "path": self.path,
            "headers": {key.lower(): value for key, value in self.headers.items()},
            "body": raw_body,
        })
        if stub.responses:
            status, body = stub.responses.pop(0)
        else:
            status, body = 200, b'{"ok": true}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-PowerContext-Request-ID", "req-stub-0001")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """不往标准输出写访问日志。"""


class _StubServer:
    """仅监听回环地址的临时 HTTP Server。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list[tuple[int, bytes]] = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        self._httpd.stub = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def respond(self, status: int, payload: object) -> None:
        self.responses.append((status, json.dumps(payload).encode("utf-8")))

    def respond_raw(self, status: int, body: bytes) -> None:
        self.responses.append((status, body))

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


class PowerContextClientTestCase(unittest.TestCase):
    """所有客户端测试共用的桩服务器。"""

    def setUp(self) -> None:
        self.server = _StubServer()
        self.addCleanup(self.server.close)
        self.client = PowerContextClient(base_url=self.server.base_url, bearer_token=TEST_TOKEN)

    def _body(self, index: int = 0) -> dict:
        return json.loads(self.server.requests[index]["body"].decode("utf-8"))


class PrepareContextTests(PowerContextClientTestCase):
    """prepare_context 的请求与响应行为。"""

    def test_向正确路径发送正确JSON(self) -> None:
        self.server.respond(200, {"status": "ready", "content": "珍珠没有手，所以不应该拥有投票权。"})

        self.client.prepare_context(scope_id="scope-1", query="珍珠 投票权", max_bytes=4000)

        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.server.requests[0]["path"], PREPARE_PATH)
        self.assertEqual(self.server.requests[0]["headers"]["content-type"], "application/json")
        self.assertEqual(
            self._body(),
            {"scope_id": "scope-1", "query": "珍珠 投票权", "max_bytes": 4000},
        )

    def test_带令牌时发送正确的Authorization头(self) -> None:
        self.server.respond(200, {"status": "ready", "content": "历史"})

        self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

        self.assertEqual(self.server.requests[0]["headers"]["authorization"], f"Bearer {TEST_TOKEN}")

    def test_无令牌时不发送Authorization头(self) -> None:
        anonymous = PowerContextClient(base_url=self.server.base_url)
        self.server.respond(200, {"status": "ready", "content": "历史"})

        anonymous.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

        self.assertNotIn("authorization", self.server.requests[0]["headers"])

    def test_ready与字符串内容返回对应结果(self) -> None:
        self.server.respond(200, {"status": "ready", "content": "上回阿强说珍珠没有手。"})

        prepared = self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

        self.assertEqual(prepared, PreparedContext(status="ready", content="上回阿强说珍珠没有手。"))

    def test_empty与null内容返回None(self) -> None:
        self.server.respond(200, {"status": "empty", "content": None})

        prepared = self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

        self.assertEqual(prepared, PreparedContext(status="empty", content=None))
        self.assertIsNone(prepared.content)

    def test_缺少content字段时返回None(self) -> None:
        self.server.respond(200, {"status": "empty"})

        prepared = self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

        self.assertIsNone(prepared.content)

    def test_状态不是字符串时抛出PowerContextError(self) -> None:
        self.server.respond(200, {"content": "历史"})

        with self.assertRaises(PowerContextError):
            self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

    def test_内容类型非法时抛出PowerContextError(self) -> None:
        self.server.respond(200, {"status": "ready", "content": 42})

        with self.assertRaises(PowerContextError):
            self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

    def test_非法参数在发出请求前失败(self) -> None:
        invalid_calls = [
            {"scope_id": "", "query": "珍珠", "max_bytes": 4000},
            {"scope_id": "scope-1", "query": "   ", "max_bytes": 4000},
            {"scope_id": "scope-1", "query": "珍珠", "max_bytes": 0},
            {"scope_id": "scope-1", "query": "珍珠", "max_bytes": -1},
            {"scope_id": "scope-1", "query": "珍珠", "max_bytes": True},
        ]
        for kwargs in invalid_calls:
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                self.client.prepare_context(**kwargs)

        self.assertEqual(self.server.requests, [])


class RecordMemoryTests(PowerContextClientTestCase):
    """record_memory 的写入顺序、载荷与失败语义。"""

    def test_先保存来源证据再写入长期记忆(self) -> None:
        self.server.respond(200, {"source": {"source_id": "src-1"}})
        self.server.respond(200, {"memory_id": "mem-1"})

        self.client.record_memory(
            scope_id="scope-1",
            source_id="src-1",
            source_content="阿强：珍珠没有手，所以不应该拥有投票权。",
            metadata={"topic_id": "pearl-voting-rights", "round": 1},
            memory_kind="stance",
            memory_text="阿强在珍珠投票权一局选择反对。",
            reason="与游戏直接相关的立场记录。",
        )

        self.assertEqual(len(self.server.requests), 2)
        self.assertEqual(self.server.requests[0]["path"], SOURCE_PATH)
        self.assertEqual(self.server.requests[1]["path"], REMEMBER_PATH)

    def test_两个写入请求的载荷恰好符合约定(self) -> None:
        self.server.respond(200, {"source": {}})
        self.server.respond(200, {"memory_id": "mem-1"})
        metadata = {"topic_id": "pearl-voting-rights"}

        self.client.record_memory(
            scope_id="scope-1",
            source_id="src-1",
            source_content="原始互动证据",
            metadata=metadata,
            memory_kind="stance",
            memory_text="记忆正文",
            reason="记忆理由",
        )

        self.assertEqual(
            self._body(0),
            {
                "scope_id": "scope-1",
                "source_id": "src-1",
                "content": "原始互动证据",
                "metadata": {"topic_id": "pearl-voting-rights"},
            },
        )
        self.assertEqual(
            self._body(1),
            {
                "scope_id": "scope-1",
                "kind": "stance",
                "text": "记忆正文",
                "reason": "记忆理由",
            },
        )
        self.assertEqual(metadata, {"topic_id": "pearl-voting-rights"})

    def test_来源请求失败时不发送第二个请求(self) -> None:
        self.server.respond_raw(500, b'{"error": {"code": "internal_error"}}')

        with self.assertRaises(PowerContextWriteError) as raised:
            self.client.record_memory(
                scope_id="scope-1",
                source_id="src-1",
                source_content="原始互动证据",
                metadata={},
                memory_kind="stance",
                memory_text="记忆正文",
                reason="记忆理由",
            )

        self.assertFalse(raised.exception.source_recorded)
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.server.requests[0]["path"], SOURCE_PATH)

    def test_记忆请求失败时标记证据已保存(self) -> None:
        self.server.respond(200, {"source": {}})
        self.server.respond_raw(422, b'{"error": {"code": "invalid_request"}}')

        with self.assertRaises(PowerContextWriteError) as raised:
            self.client.record_memory(
                scope_id="scope-1",
                source_id="src-1",
                source_content="原始互动证据",
                metadata={},
                memory_kind="stance",
                memory_text="记忆正文",
                reason="记忆理由",
            )

        self.assertTrue(raised.exception.source_recorded)
        self.assertEqual(len(self.server.requests), 2)

    def test_非法参数在发出请求前失败(self) -> None:
        base = {
            "scope_id": "scope-1",
            "source_id": "src-1",
            "source_content": "原始互动证据",
            "metadata": {},
            "memory_kind": "stance",
            "memory_text": "记忆正文",
            "reason": "记忆理由",
        }
        invalid = [
            {**base, "scope_id": ""},
            {**base, "source_id": ""},
            {**base, "source_content": "  "},
            {**base, "memory_kind": ""},
            {**base, "memory_text": ""},
            {**base, "reason": ""},
            {**base, "metadata": "not-a-mapping"},
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                self.client.record_memory(**kwargs)

        self.assertEqual(self.server.requests, [])


class ErrorHandlingTests(PowerContextClientTestCase):
    """外部失败的可观察诊断信息。"""

    def test_服务器返回非JSON时抛出明确异常(self) -> None:
        self.server.respond_raw(200, b"this is not json")

        with self.assertRaises(PowerContextError) as raised:
            self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

        self.assertIn("JSON", str(raised.exception))

    def test_服务器返回非对象JSON时抛出明确异常(self) -> None:
        self.server.respond_raw(200, b"[1, 2, 3]")

        with self.assertRaises(PowerContextError) as raised:
            self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

        self.assertIn("对象", str(raised.exception))

    def test_HTTP错误包含状态与截断后的正文(self) -> None:
        self.server.respond_raw(400, b"x" * 900)

        with self.assertRaises(PowerContextError) as raised:
            self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

        message = str(raised.exception)
        self.assertIn("400", message)
        self.assertIn("响应体前 500 字符", message)
        self.assertLess(len(message), 700)

    def test_异常文本不包含测试令牌(self) -> None:
        self.server.respond_raw(401, f'{{"detail": "{TEST_TOKEN}"}}'.encode())

        with self.assertRaises(PowerContextError) as raised:
            self.client.prepare_context(scope_id="scope-1", query="珍珠", max_bytes=4000)

        self.assertNotIn(TEST_TOKEN, str(raised.exception))

    def test_写入失败的异常文本不包含测试令牌(self) -> None:
        self.server.respond_raw(403, f'{{"detail": "{TEST_TOKEN}"}}'.encode())

        with self.assertRaises(PowerContextWriteError) as raised:
            self.client.record_memory(
                scope_id="scope-1",
                source_id="src-1",
                source_content="原始互动证据",
                metadata={},
                memory_kind="stance",
                memory_text="记忆正文",
                reason="记忆理由",
            )

        self.assertNotIn(TEST_TOKEN, str(raised.exception))

    def test_客户端表示形式不包含令牌(self) -> None:
        self.assertNotIn(TEST_TOKEN, repr(self.client))


class ConstructorTests(unittest.TestCase):
    """构造器的参数规则。"""

    def test_去掉末尾多余斜杠(self) -> None:
        client = PowerContextClient(base_url="http://127.0.0.1:8000///")

        normalized = repr(client).split("base_url='")[1].split("'")[0]
        self.assertEqual(normalized, "http://127.0.0.1:8000")

    def test_拒绝非HTTP协议(self) -> None:
        for url in ("ftp://127.0.0.1", "file:///tmp/x", "127.0.0.1:8000"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                PowerContextClient(base_url=url)

    def test_拒绝缺少主机的地址(self) -> None:
        for url in ("http://", "https://"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                PowerContextClient(base_url=url)

    def test_超时必须是大于零的数值(self) -> None:
        with self.assertRaises(ValueError):
            PowerContextClient(base_url="http://127.0.0.1:8000", timeout_seconds=0)
        with self.assertRaises(ValueError):
            PowerContextClient(base_url="http://127.0.0.1:8000", timeout_seconds=-1.5)
        with self.assertRaises(TypeError):
            PowerContextClient(base_url="http://127.0.0.1:8000", timeout_seconds="10")

    def test_非有限超时值被拒绝(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(timeout_seconds=value), self.assertRaises(ValueError):
                PowerContextClient(base_url="http://127.0.0.1:8000", timeout_seconds=value)

    def test_非法超时取值全部被拒绝(self) -> None:
        invalid = [
            True,
            False,
            "10",
            None,
            0,
            -1,
            0.0,
            -0.5,
            float("nan"),
            float("inf"),
            float("-inf"),
        ]
        for value in invalid:
            with self.subTest(timeout_seconds=value), self.assertRaises((TypeError, ValueError)):
                PowerContextClient(base_url="http://127.0.0.1:8000", timeout_seconds=value)

    def test_合法超时取值可以构造(self) -> None:
        for value in (1, 1.5, 0.01):
            with self.subTest(timeout_seconds=value):
                client = PowerContextClient(base_url="http://127.0.0.1:8000", timeout_seconds=value)
                self.assertIsInstance(client, PowerContextClient)

    def test_空令牌视为不发送认证头(self) -> None:
        client = PowerContextClient(base_url="http://127.0.0.1:8000", bearer_token="")

        self.assertNotIn("authenticated=True", repr(client))


if __name__ == "__main__":
    unittest.main()
