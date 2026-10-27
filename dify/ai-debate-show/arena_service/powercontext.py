"""PowerContext HTTP 记忆客户端。

只使用 Python 标准库的 ``urllib.request`` 发起同步请求，不依赖任何第三方库、
网络服务、环境变量或模型能力。

本客户端只覆盖三个已确认的 PowerContext 操作：

* ``POST /v1/context/prepare`` —— 生成内容前准备与当前辩题相关的历史上下文；
* ``POST /v1/sources/content`` —— 结算后保存本局原始游戏互动证据；
* ``POST /v1/memory/remember`` —— 证据保存成功后写入长期记忆。

Scope 只能由调用方显式传入：客户端不会创建 Scope，也不会从模型输出、
玩家文本或历史记忆中推导 ``scope_id``。
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

__all__ = [
    "PowerContextClient",
    "PowerContextError",
    "PowerContextWriteError",
    "PreparedContext",
]

PREPARE_PATH = "/v1/context/prepare"
SOURCE_PATH = "/v1/sources/content"
REMEMBER_PATH = "/v1/memory/remember"

MAX_ERROR_BODY_CHARS = 500
REDACTED = "***"


@dataclass(frozen=True)
class PreparedContext:
    """一次 ``/v1/context/prepare`` 的结果。"""

    status: str
    content: str | None


class PowerContextError(RuntimeError):
    """PowerContext 调用失败。"""


class PowerContextWriteError(PowerContextError):
    """写入过程中失败。

    ``source_recorded`` 表示本局的原始互动证据是否已经成功保存：
    ``False`` 表示证据都没存下来，``True`` 表示证据已保存但长期记忆没写成。
    """

    def __init__(self, message: str, *, source_recorded: bool) -> None:
        super().__init__(message)
        self.source_recorded = source_recorded


class PowerContextClient:
    """同步的 PowerContext HTTP 客户端。"""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        """构造客户端。

        Args:
            base_url: PowerContext Server 根地址，必须是 http 或 https 且带主机名。
            bearer_token: 可选的 Bearer 令牌；为 ``None`` 或空串时不发送 Authorization 头。
            timeout_seconds: 单次请求超时秒数，必须是大于 0 的有限数值。

        Raises:
            TypeError: 参数类型不正确。
            ValueError: 参数值不可用（非 http(s) 地址、缺少主机名、非正或非有限超时）。
        """
        self._base_url = _normalize_base_url(base_url)
        self._timeout_seconds = _normalize_timeout(timeout_seconds)
        if bearer_token is None:
            self._bearer_token: str | None = None
        elif not isinstance(bearer_token, str):
            raise TypeError(f"bearer_token 必须是字符串或 None，实际为 {type(bearer_token).__name__}")
        else:
            self._bearer_token = bearer_token or None

    def __repr__(self) -> str:
        """不包含令牌的表示形式。"""
        return (
            f"PowerContextClient(base_url={self._base_url!r}, "
            f"timeout_seconds={self._timeout_seconds!r}, "
            f"authenticated={self._bearer_token is not None})"
        )

    # ------------------------------------------------------------------ #
    # 公开操作
    # ------------------------------------------------------------------ #

    def prepare_context(
        self,
        *,
        scope_id: str,
        query: str,
        max_bytes: int,
    ) -> PreparedContext:
        """准备与当前辩题相关的历史上下文。

        Args:
            scope_id: 调用方显式指定的 Scope，必须是非空字符串。
            query: 检索用的查询文本，必须是非空字符串。
            max_bytes: 返回内容的字节上限，必须是正整数（布尔值不算整数）。

        Returns:
            :class:`PreparedContext`；没有可用历史时 ``content`` 为 ``None``。

        Raises:
            TypeError: 参数类型不正确。
            ValueError: 参数值为空或不合法。
            PowerContextError: 请求失败，或响应结构不符合约定。
        """
        scope_id = _require_text(scope_id, "scope_id")
        query = _require_text(query, "query")
        max_bytes = _require_positive_int(max_bytes, "max_bytes")

        payload = {"scope_id": scope_id, "query": query, "max_bytes": max_bytes}
        document = self._post_json(PREPARE_PATH, payload, operation="准备上下文")

        status = document.get("status")
        if not isinstance(status, str):
            raise PowerContextError(f"准备上下文（{PREPARE_PATH}）失败：响应缺少字符串字段 'status'")
        content = document.get("content")
        if content is None:
            return PreparedContext(status=status, content=None)
        if not isinstance(content, str):
            raise PowerContextError(
                f"准备上下文（{PREPARE_PATH}）失败：响应字段 'content' "
                f"必须是字符串或 null，实际为 {type(content).__name__}"
            )
        return PreparedContext(status=status, content=content)

    def record_memory(
        self,
        *,
        scope_id: str,
        source_id: str,
        source_content: str,
        metadata: Mapping[str, object],
        memory_kind: str,
        memory_text: str,
        reason: str,
    ) -> None:
        """先保存原始互动证据，再写入长期记忆。

        顺序固定：``/v1/sources/content`` 成功之后才会调用 ``/v1/memory/remember``。
        第一步失败时不会发送第二个请求；任一步失败都不自动重试。

        Args:
            scope_id: 调用方显式指定的 Scope。
            source_id: 调用方提供的证据标识，客户端不会自动生成。
            source_content: 本局原始互动证据正文。
            metadata: 附加元数据，客户端不会修改调用方传入的对象。
            memory_kind: 记忆类型，例如立场、名言、人设标签。
            memory_text: 记忆正文。
            reason: 写入这条记忆的理由。

        Raises:
            TypeError: 参数类型不正确。
            ValueError: 参数值为空或不合法。
            PowerContextWriteError: 写入失败；``source_recorded`` 指出证据是否已保存。
        """
        scope_id = _require_text(scope_id, "scope_id")
        source_id = _require_text(source_id, "source_id")
        source_content = _require_text(source_content, "source_content")
        memory_kind = _require_text(memory_kind, "memory_kind")
        memory_text = _require_text(memory_text, "memory_text")
        reason = _require_text(reason, "reason")
        if not isinstance(metadata, Mapping):
            raise TypeError(f"metadata 必须是 Mapping，实际为 {type(metadata).__name__}")

        source_payload = {
            "scope_id": scope_id,
            "source_id": source_id,
            "content": source_content,
            "metadata": dict(metadata),
        }
        try:
            self._post_json(SOURCE_PATH, source_payload, operation="保存来源证据")
        except PowerContextError as exc:
            raise PowerContextWriteError(str(exc), source_recorded=False) from exc

        memory_payload = {
            "scope_id": scope_id,
            "kind": memory_kind,
            "text": memory_text,
            "reason": reason,
        }
        try:
            self._post_json(REMEMBER_PATH, memory_payload, operation="写入长期记忆")
        except PowerContextError as exc:
            raise PowerContextWriteError(str(exc), source_recorded=True) from exc

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #

    def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        operation: str,
    ) -> dict[str, Any]:
        """发送一次 JSON POST，并要求响应是 JSON 对象。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"

        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                status_code = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise self._error(
                f"{operation}（{path}）失败：HTTP {exc.code} {exc.reason}；"
                f"{_describe_body(exc.read())}"
                f"{_describe_request_id(exc.headers)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise self._error(f"{operation}（{path}）失败：网络错误（{exc.reason}）") from exc
        except TimeoutError as exc:
            raise self._error(f"{operation}（{path}）失败：请求超时（{self._timeout_seconds} 秒）") from exc
        except OSError as exc:
            raise self._error(f"{operation}（{path}）失败：网络错误（{exc}）") from exc

        if not 200 <= status_code <= 299:
            raise self._error(f"{operation}（{path}）失败：HTTP {status_code}；{_describe_body(raw)}")

        try:
            document = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise self._error(f"{operation}（{path}）失败：响应不是合法的 UTF-8 文本") from exc
        except json.JSONDecodeError as exc:
            raise self._error(f"{operation}（{path}）失败：响应不是合法 JSON（{exc.msg}）") from exc

        if not isinstance(document, dict):
            raise self._error(f"{operation}（{path}）失败：响应 JSON 顶层不是对象（实际为 {type(document).__name__}）")
        return document

    def _error(self, message: str) -> PowerContextError:
        """构造异常，并确保令牌不出现在消息中。"""
        return PowerContextError(self._redact(message))

    def _redact(self, text: str) -> str:
        """把可能出现在服务响应里的令牌替换掉。"""
        if self._bearer_token:
            return text.replace(self._bearer_token, REDACTED)
        return text


# --------------------------------------------------------------------------- #
# 参数校验
# --------------------------------------------------------------------------- #


def _normalize_base_url(base_url: str) -> str:
    """校验并规范化根地址。"""
    if not isinstance(base_url, str):
        raise TypeError(f"base_url 必须是字符串，实际为 {type(base_url).__name__}")
    text = base_url.strip()
    if not text:
        raise ValueError("base_url 不能为空")
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise ValueError(f"base_url 不是合法的 URL（{exc}）") from exc
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"base_url 必须使用 http 或 https 协议，实际为 {parts.scheme!r}")
    if not parts.netloc or not parts.hostname:
        raise ValueError("base_url 必须包含主机名")
    return text.rstrip("/")


def _normalize_timeout(timeout_seconds: float) -> float:
    """校验超时秒数。

    有效定义：类型是 ``int`` 或 ``float``（布尔值不算数值）、是有限数、严格大于 0。
    NaN 与正负 Infinity 都不是真实可用的时长，必须在构造阶段被拒绝。
    """
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise TypeError(f"timeout_seconds 必须是数值，实际为 {type(timeout_seconds).__name__}")
    try:
        is_finite = math.isfinite(timeout_seconds)
    except OverflowError as exc:
        raise ValueError(f"timeout_seconds 必须是有限数，实际为 {timeout_seconds}") from exc
    if not is_finite:
        raise ValueError(f"timeout_seconds 必须是有限数，实际为 {timeout_seconds}")
    if timeout_seconds <= 0:
        raise ValueError(f"timeout_seconds 必须大于 0，实际为 {timeout_seconds}")
    return float(timeout_seconds)


def _require_text(value: object, field: str) -> str:
    """要求非空字符串；原样返回，不修改调用方传入的值。"""
    if not isinstance(value, str):
        raise TypeError(f"{field} 必须是字符串，实际为 {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{field} 不能为空字符串")
    return value


def _require_positive_int(value: object, field: str) -> int:
    """要求正整数；布尔值不算整数。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} 必须是正整数（布尔值不算整数），实际为 {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"{field} 必须大于 0，实际为 {value}")
    return value


def _describe_body(raw: bytes) -> str:
    """把错误响应正文压缩成最多 500 字符的诊断信息。"""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return "响应体为空"
    if len(text) > MAX_ERROR_BODY_CHARS:
        return f"响应体前 {MAX_ERROR_BODY_CHARS} 字符：{text[:MAX_ERROR_BODY_CHARS]}…"
    return f"响应体：{text}"


def _describe_request_id(headers: Any) -> str:
    """把服务端返回的请求 ID 带上，便于诊断。"""
    if headers is None:
        return ""
    request_id = headers.get("X-PowerContext-Request-ID")
    if not request_id:
        return ""
    return f"（request_id={request_id}）"
