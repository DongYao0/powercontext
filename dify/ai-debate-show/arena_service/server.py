"""Arena 本地 HTTP 服务。

可以直接执行：

.. code-block:: powershell

    $env:PYTHONPATH = "dify/ai-debate-show"
    python -m arena_service.server

服务只做编排与确定性计算，**不生成任何模型文案**：主持人与对手的措辞由 Dify
侧的模型产出，本服务提供卡片原文、追问、立场与回合状态。

配置全部来自环境变量，代码与文档中都不写入真实令牌：

.. code-block:: text

    ARENA_HOST=127.0.0.1
    ARENA_PORT=8088
    POWERCONTEXT_BASE_URL=...
    POWERCONTEXT_BEARER_TOKEN=...
    POWERCONTEXT_TIMEOUT_SECONDS=10

未配置 ``POWERCONTEXT_BASE_URL`` 时，记忆能力降级：对局照常可玩，只是没有
"翻旧账"的历史上下文，记忆写入端点返回 503。
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .app import (
    ArenaApplication,
    ArenaApplicationError,
    GameNotFoundError,
    MemoryUnavailableError,
)
from .content import load_content_catalog
from .game import GAME_ACTIONS, GameInputError, RoundPlan
from .game_memory import GameMemoryValidationError
from .powercontext import PowerContextClient, PowerContextError, PowerContextWriteError

__all__ = ["build_application", "create_server", "main"]

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content-draft"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8088
DEFAULT_TIMEOUT_SECONDS = 10.0
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
REDACTED = "***"

ERROR_INVALID_REQUEST = "invalid_request"
ERROR_GAME_NOT_FOUND = "game_not_found"
ERROR_INVALID_STATE = "invalid_state"
ERROR_MEMORY_UNAVAILABLE = "memory_unavailable"
ERROR_POWERCONTEXT = "powercontext_error"
ERROR_INTERNAL = "internal_error"
ERROR_NOT_FOUND = "not_found"
ERROR_METHOD_NOT_ALLOWED = "method_not_allowed"


class _BadRequest(Exception):
    """请求本身不合法，对应 400。"""


class ArenaRequestHandler(BaseHTTPRequestHandler):
    """把 Arena 应用层暴露成 JSON HTTP 接口。"""

    server_version = "ArenaService/0.1"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ #
    # 路由
    # ------------------------------------------------------------------ #

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "ai-debate-show",
                    "memory_configured": self._application.powercontext_configured,
                },
            )
            return
        self._send_error(404, ERROR_NOT_FOUND, f"未知的接口路径：{path}")

    def do_POST(self) -> None:
        try:
            path = urlsplit(self.path).path
            segments = [segment for segment in path.split("/") if segment]
            if segments == ["games"]:
                self._handle_create_game()
                return
            if len(segments) == 3 and segments[0] == "games" and segments[2] == "rounds":
                self._handle_play_round(unquote(segments[1]))
                return
            if len(segments) == 3 and segments[0] == "games" and segments[2] == "memory":
                self._handle_record_memory(unquote(segments[1]))
                return
            self._send_error(404, ERROR_NOT_FOUND, f"未知的接口路径：{path}")
        except _BadRequest as exc:
            self._send_error(400, ERROR_INVALID_REQUEST, str(exc))
        except MemoryUnavailableError as exc:
            self._send_error(503, ERROR_MEMORY_UNAVAILABLE, str(exc))
        except GameNotFoundError as exc:
            self._send_error(404, ERROR_GAME_NOT_FOUND, str(exc))
        except ArenaApplicationError as exc:
            self._send_error(409, ERROR_INVALID_STATE, str(exc))
        except (GameInputError, GameMemoryValidationError) as exc:
            self._send_error(400, ERROR_INVALID_REQUEST, str(exc))
        except PowerContextWriteError as exc:
            self._send_error(
                502,
                ERROR_POWERCONTEXT,
                str(exc),
                details={"source_recorded": exc.source_recorded},
            )
        except PowerContextError as exc:
            self._send_error(502, ERROR_POWERCONTEXT, str(exc))
        except Exception:
            self._send_error(500, ERROR_INTERNAL, "服务内部错误")

    def do_PUT(self) -> None:
        self._send_error(405, ERROR_METHOD_NOT_ALLOWED, "该路径不支持 PUT 方法")

    def do_PATCH(self) -> None:
        self._send_error(405, ERROR_METHOD_NOT_ALLOWED, "该路径不支持 PATCH 方法")

    def do_DELETE(self) -> None:
        self._send_error(405, ERROR_METHOD_NOT_ALLOWED, "该路径不支持 DELETE 方法")

    def do_HEAD(self) -> None:
        self._send_error(405, ERROR_METHOD_NOT_ALLOWED, "该路径不支持 HEAD 方法")

    def do_OPTIONS(self) -> None:
        self._send_error(405, ERROR_METHOD_NOT_ALLOWED, "该路径不支持 OPTIONS 方法")

    # ------------------------------------------------------------------ #
    # 端点处理
    # ------------------------------------------------------------------ #

    def _handle_create_game(self) -> None:
        payload = self._read_json_object()
        session = self._application.start_game(
            game_id=self._require_field(payload, "game_id"),
            scope_id=self._require_field(payload, "scope_id"),
            player_nickname=self._require_field(payload, "player_nickname"),
            topic_id=self._require_field(payload, "topic_id"),
            initial_stance=self._require_field(payload, "initial_stance"),
            opponent_id=self._require_field(payload, "opponent_id"),
        )
        state = session.state
        self._send_json(
            201,
            {
                "game_id": state.game_id,
                "scope_id": session.scope_id,
                "player_nickname": state.player_nickname,
                "topic_id": state.topic_id,
                "topic_title": session.topic_title,
                "opponent_id": state.opponent_id,
                "current_stance": state.current_stance,
                "completed_rounds": state.completed_rounds,
                "memory_context": session.memory_context,
                "memory_status": session.memory_status,
                "available_actions": list(GAME_ACTIONS),
            },
        )

    def _handle_play_round(self, game_id: str) -> None:
        payload = self._read_json_object()
        plan = self._application.play_round(
            game_id=game_id,
            player_action=self._require_field(payload, "player_action"),
            player_message=self._require_field(payload, "player_message"),
        )
        self._send_json(200, _round_plan_payload(plan))

    def _handle_record_memory(self, game_id: str) -> None:
        payload = self._read_json_object()
        self._application.record_final_memory(
            game_id=game_id,
            player_message=self._require_field(payload, "player_message"),
            memory_kind=self._require_field(payload, "memory_kind"),
            memory_text=self._require_field(payload, "memory_text"),
            reason=self._require_field(payload, "reason"),
        )
        self._send_json(200, {"status": "recorded"})

    # ------------------------------------------------------------------ #
    # 基础工具
    # ------------------------------------------------------------------ #

    @property
    def _application(self) -> ArenaApplication:
        return self.server.application  # type: ignore[attr-defined]

    def _read_json_object(self) -> dict[str, Any]:
        """读取并解析请求体；不是 JSON 对象时抛出 400。"""
        content_type = self.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise _BadRequest("请求 Content-Type 必须是 application/json")

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise _BadRequest("Content-Length 必须是合法整数") from None
        if length < 0:
            raise _BadRequest("Content-Length 必须是合法整数")

        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise _BadRequest("请求正文不是合法的 UTF-8 文本") from None
        except json.JSONDecodeError:
            raise _BadRequest("请求正文不是合法 JSON") from None
        if not isinstance(payload, dict):
            raise _BadRequest("请求正文必须是 JSON 对象")
        return payload

    def _require_field(self, payload: dict[str, Any], name: str) -> str:
        """取出必需的字符串字段，缺失或类型不对都算 400。"""
        if name not in payload:
            raise _BadRequest(f"缺少必需字段 {name!r}")
        value = payload[name]
        if not isinstance(value, str):
            raise _BadRequest(f"字段 {name!r} 必须是字符串")
        return value

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        details: dict[str, Any] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """统一错误格式；消息中的敏感值会被替换掉。"""
        error: dict[str, Any] = {"code": code, "message": self._redact(message)}
        if details is not None:
            error["details"] = details
        self._send_json(status, {"error": error})

    def _redact(self, text: str) -> str:
        """确保服务持有的敏感值不会出现在响应里。"""
        for secret in getattr(self.server, "secrets", ()):
            if secret:
                text = text.replace(secret, REDACTED)
        return text

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "quiet", True):
            return
        super().log_message(fmt, *args)


def _round_plan_payload(plan: RoundPlan) -> dict[str, Any]:
    """把回合计划转成 JSON 友好结构。"""
    state = plan.state
    return {
        "round_number": plan.round_number,
        "player_action": plan.player_action,
        "player_message": plan.player_message,
        "selected_card_id": plan.selected_card_id,
        "opponent_message": plan.opponent_message,
        "follow_up_question": plan.follow_up_question,
        "card_reused": plan.card_reused,
        "game_finished": plan.game_finished,
        "state": {
            "game_id": state.game_id,
            "player_nickname": state.player_nickname,
            "topic_id": state.topic_id,
            "opponent_id": state.opponent_id,
            "current_stance": state.current_stance,
            "completed_rounds": state.completed_rounds,
            "used_card_ids": list(state.used_card_ids),
            "finished": state.finished,
        },
        "available_actions": list(GAME_ACTIONS),
    }


def build_application(content_directory: Path | None = None) -> ArenaApplication:
    """按环境变量装配应用层。"""
    catalog = load_content_catalog(content_directory or CONTENT_DIR)
    return ArenaApplication(catalog, build_powercontext_client())


def build_powercontext_client() -> PowerContextClient | None:
    """按环境变量构造记忆客户端；未配置时返回 None 表示降级。"""
    base_url = (os.environ.get("POWERCONTEXT_BASE_URL") or "").strip()
    if not base_url:
        return None
    token = (os.environ.get("POWERCONTEXT_BEARER_TOKEN") or "").strip() or None
    return PowerContextClient(
        base_url=base_url,
        bearer_token=token,
        timeout_seconds=_read_timeout_seconds(),
    )


def _read_timeout_seconds() -> float:
    raw = (os.environ.get("POWERCONTEXT_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("POWERCONTEXT_TIMEOUT_SECONDS 必须是大于 0 的数值") from None
    if value <= 0 or value != value or value in (float("inf"), float("-inf")):
        raise ValueError("POWERCONTEXT_TIMEOUT_SECONDS 必须是大于 0 的有限数值")
    return value


def create_server(
    host: str,
    port: int,
    application: ArenaApplication,
    *,
    quiet: bool = True,
    secrets: tuple[str, ...] = (),
) -> ThreadingHTTPServer:
    """创建（但不启动）HTTP 服务实例。"""
    httpd = ThreadingHTTPServer((host, port), ArenaRequestHandler)
    httpd.application = application  # type: ignore[attr-defined]
    httpd.quiet = quiet  # type: ignore[attr-defined]
    httpd.secrets = tuple(secrets)  # type: ignore[attr-defined]
    return httpd


def main() -> int:
    """启动服务并阻塞运行，Ctrl+C 时干净退出。"""
    host = (os.environ.get("ARENA_HOST") or "").strip() or DEFAULT_HOST
    port = _read_port()
    application = build_application()
    token = (os.environ.get("POWERCONTEXT_BEARER_TOKEN") or "").strip()
    secrets = (token,) if token else ()
    httpd = create_server(host, port, application, quiet=False, secrets=secrets)
    print(f"Arena 服务已启动：http://{host}:{port}", file=sys.stderr)
    print("记忆能力：" + ("已配置" if application.powercontext_configured else "未配置（降级）"), file=sys.stderr)
    print("按 Ctrl+C 停止。", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止 Arena 服务……", file=sys.stderr)
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


def _read_port() -> int:
    raw = (os.environ.get("ARENA_PORT") or "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError("ARENA_PORT 必须是合法端口号") from None
    if not 0 < port < 65536:
        raise ValueError("ARENA_PORT 必须是 1-65535 之间的端口号")
    return port


if __name__ == "__main__":
    raise SystemExit(main())
