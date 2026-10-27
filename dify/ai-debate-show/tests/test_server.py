"""Arena HTTP 服务的端到端测试。

在临时端口上启动真实的 ThreadingHTTPServer，全部流量只走本机回环地址，
不访问外网，也不启动真实 PowerContext。
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from arena_service import ArenaApplication, load_content_catalog
from arena_service.powercontext import PowerContextClient
from arena_service.server import create_server

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content-draft"
TEST_TOKEN = "arena-test-token-4b7d1e"
GAME_ID = "game-http-001"
SCOPE_ID = "trusted-scope-id"
NICKNAME = "阿强"
TOPIC_ID = "pearl-voting-rights"
OPPONENT_ID = "logic-monster"


class _StubPowerContextHandler(BaseHTTPRequestHandler):
    """回显令牌的假 PowerContext，用于验证令牌不会泄漏。"""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.dumps({"detail": f"token={TEST_TOKEN}"}).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """不写访问日志。"""


class _StubPowerContext:
    """只监听回环地址的假 PowerContext。"""

    def __init__(self) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _StubPowerContextHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


class ArenaServerTestCase(unittest.TestCase):
    """共用的 Arena 服务与 HTTP 调用helper。"""

    def setUp(self) -> None:
        self.application = ArenaApplication(load_content_catalog(CONTENT_DIR), None)
        self.httpd = create_server("127.0.0.1", 0, self.application, quiet=True)
        self.addCleanup(self._shutdown)
        self._thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()
        host, port = self.httpd.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def _shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, dict]:
        """发起一次请求并返回状态码与解析后的 JSON。"""
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = content_type
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
                body = response.read()
                content_type_header = response.headers.get("Content-Type")
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read()
            content_type_header = exc.headers.get("Content-Type")

        self.assertEqual(content_type_header, "application/json; charset=utf-8")
        return status, json.loads(body.decode("utf-8"))

    def create_game(self, game_id: str = GAME_ID) -> dict:
        status, body = self.request(
            "POST",
            "/games",
            {
                "game_id": game_id,
                "scope_id": SCOPE_ID,
                "player_nickname": NICKNAME,
                "topic_id": TOPIC_ID,
                "initial_stance": "反对",
                "opponent_id": OPPONENT_ID,
            },
        )
        self.assertEqual(status, 201)
        return body

    def play_round(self, game_id: str = GAME_ID, message: str = "珍珠没有手。") -> dict:
        status, body = self.request(
            "POST",
            f"/games/{game_id}/rounds",
            {"player_action": "double_down", "player_message": message},
        )
        self.assertEqual(status, 200)
        return body


class HealthTests(ArenaServerTestCase):
    """健康检查。"""

    def test_健康检查返回ok(self) -> None:
        status, body = self.request("GET", "/health")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertFalse(body["memory_configured"])


class FullFlowTests(ArenaServerTestCase):
    """完整对局流程。"""

    def test_创建推进到结算写记忆的完整流程(self) -> None:
        created = self.create_game()
        self.assertEqual(created["memory_status"], "degraded")
        self.assertIsNone(created["memory_context"])
        self.assertEqual(created["available_actions"][0], "double_down")

        first = self.play_round()
        self.assertEqual(first["round_number"], 1)
        self.assertTrue(first["opponent_message"])
        self.assertTrue(first["follow_up_question"])
        self.assertFalse(first["game_finished"])

        self.play_round(message="第二回合")
        third = self.play_round(message="第三回合")
        self.assertTrue(third["game_finished"])
        self.assertEqual(third["state"]["completed_rounds"], 3)
        self.assertTrue(third["state"]["finished"])

        # 未配置 PowerContext 时记忆写入应返回 503
        status, body = self.request(
            "POST",
            f"/games/{GAME_ID}/memory",
            {
                "player_message": "第三回合玩家实际发言",
                "memory_kind": "stance",
                "memory_text": "阿强在珍珠投票权一局选择反对。",
                "reason": "属于与游戏直接相关的立场与理由。",
            },
        )
        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "memory_unavailable")


class ErrorResponseTests(ArenaServerTestCase):
    """错误响应格式。"""

    def test_非法JSON返回400(self) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/games",
            data=b"{not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=10)

        body = json.loads(raised.exception.read().decode("utf-8"))
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

    def test_缺字段返回400(self) -> None:
        status, body = self.request("POST", "/games", {"game_id": "g1"})

        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

    def test_请求体不是JSON对象返回400(self) -> None:
        status, body = self.request("POST", "/games", ["not", "an", "object"])

        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

    def test_非JSON内容类型返回400(self) -> None:
        status, body = self.request("POST", "/games", {"game_id": "g1"}, content_type="text/plain")

        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

    def test_不存在game_id返回404(self) -> None:
        status, body = self.request(
            "POST",
            "/games/no-such-game/rounds",
            {"player_action": "double_down", "player_message": "珍珠没有手。"},
        )

        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "game_not_found")

    def test_重复game_id返回409(self) -> None:
        self.create_game()

        status, body = self.request(
            "POST",
            "/games",
            {
                "game_id": GAME_ID,
                "scope_id": SCOPE_ID,
                "player_nickname": NICKNAME,
                "topic_id": TOPIC_ID,
                "initial_stance": "反对",
                "opponent_id": OPPONENT_ID,
            },
        )

        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "invalid_state")

    def test_游戏未结束就写记忆返回409(self) -> None:
        self.create_game()
        self.play_round()

        status, body = self.request(
            "POST",
            f"/games/{GAME_ID}/memory",
            {
                "player_message": "还没结束",
                "memory_kind": "stance",
                "memory_text": "记忆正文",
                "reason": "理由",
            },
        )

        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "invalid_state")

    def test_未知路径返回404(self) -> None:
        status, body = self.request("GET", "/nope")

        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "not_found")

    def test_不支持的方法返回405(self) -> None:
        status, body = self.request("DELETE", "/games")

        self.assertEqual(status, 405)
        self.assertEqual(body["error"]["code"], "method_not_allowed")


class TokenLeakTests(unittest.TestCase):
    """令牌不得出现在任何响应里。"""

    def test_令牌不会出现在错误响应中(self) -> None:
        stub = _StubPowerContext()
        self.addCleanup(stub.close)
        client = PowerContextClient(base_url=stub.base_url, bearer_token=TEST_TOKEN)
        application = ArenaApplication(load_content_catalog(CONTENT_DIR), client)
        httpd = create_server("127.0.0.1", 0, application, quiet=True, secrets=(TEST_TOKEN,))
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()

        def close_httpd() -> None:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        self.addCleanup(close_httpd)
        host, port = httpd.server_address[:2]
        base_url = f"http://{host}:{port}"

        def call(method: str, path: str, payload: object | None = None):
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Content-Type": "application/json"} if data else {}
            request = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    return response.status, response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8")

        status, raw = call(
            "POST",
            "/games",
            {
                "game_id": "token-game",
                "scope_id": SCOPE_ID,
                "player_nickname": NICKNAME,
                "topic_id": TOPIC_ID,
                "initial_stance": "反对",
                "opponent_id": OPPONENT_ID,
            },
        )
        self.assertEqual(status, 201)
        self.assertNotIn(TEST_TOKEN, raw)

        # 让三回合跑完，再触发记忆写入失败
        for index in range(3):
            call(
                "POST",
                "/games/token-game/rounds",
                {"player_action": "double_down", "player_message": f"第{index + 1}回合"},
            )
        status, raw = call(
            "POST",
            "/games/token-game/memory",
            {
                "player_message": "第三回合发言",
                "memory_kind": "stance",
                "memory_text": "记忆正文",
                "reason": "理由",
            },
        )
        self.assertEqual(status, 502)
        self.assertNotIn(TEST_TOKEN, raw)

        body = json.loads(raw)
        self.assertEqual(body["error"]["code"], "powercontext_error")
        self.assertIn("details", body["error"])
        self.assertIn("source_recorded", body["error"]["details"])


if __name__ == "__main__":
    unittest.main()
