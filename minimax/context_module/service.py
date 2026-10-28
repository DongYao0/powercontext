"""Issue context retrieval, MiniMax invocation, and PowerContext state reuse."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from powercontext.client import PowerContextClient
from powercontext.http import RememberMemoryRequest, SearchMemoryRequest


@dataclass(frozen=True)
class ContextModuleConfig:
    server_url: str
    scope_id: str
    minimax_url: str | None = None
    minimax_model: str = "MiniMax-M3"
    minimax_api_key: str | None = None

    @classmethod
    def from_env(cls) -> ContextModuleConfig:
        server_url = os.environ.get("POWERCONTEXT_BASE_URL")
        scope_id = os.environ.get("MINIMAX_CONTEXT_SCOPE", "goalflow-213")
        if not server_url:
            raise RuntimeError("POWERCONTEXT_BASE_URL is required")  # noqa: TRY003
        return cls(
            server_url=server_url,
            scope_id=scope_id,
            minimax_url=os.environ.get("MINIMAX_CHAT_URL"),
            minimax_model=os.environ.get("MINIMAX_MODEL", "MiniMax-M3"),
            minimax_api_key=os.environ.get("MINIMAX_API_KEY"),
        )


class ContextModule:
    """Small orchestration facade with one explicit input/output boundary."""

    def __init__(
        self,
        config: ContextModuleConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._http_client = http_client
        self._active_scope_id: str | None = None

    def _client(self, timeout: float) -> PowerContextClient:
        return PowerContextClient(
            self.config.server_url,
            timeout=timeout,
            http_client=self._http_client,
            trust_transport_security=self._http_client is not None,
        )

    @property
    def scope_id(self) -> str:
        return self._active_scope_id or self.config.scope_id

    async def initialize(self) -> dict[str, Any]:
        """Create the durable PowerContext scope if it does not exist."""

        async with self._client(30) as client:
            scope = await client.get_default_scope()
            self._active_scope_id = scope.scope_id
            return {"scope_id": scope.scope_id, "created": False}

    async def import_sources(self, sources: list[dict[str, str]]) -> list[dict[str, str]]:
        """Store source-labelled specs, code, and tests in PowerContext memory."""

        saved: list[dict[str, str]] = []
        async with self._client(60) as client:
            for source in sources:
                source_id = source["source_id"]
                text = f"SOURCE_ID: {source_id}\nSOURCE_KIND: {source['kind']}\n\n{source['text']}"
                result = await client.remember_memory(
                    RememberMemoryRequest(
                        scope_id=self.scope_id,
                        kind=f"goalflow-213-{source['kind']}",
                        text=text,
                        reason="GoalFlow Issue 213 SDD context import",
                    )
                )
                saved.append({"source_id": source_id, "memory_id": result.memory.artifact_id})
        return saved

    async def build_context(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        """Search the database and return source-labelled context for an agent."""

        async with self._client(60) as client:
            result = await client.search_memory(SearchMemoryRequest(scope_id=self.scope_id, query=query, limit=limit))
        hits = []
        for hit in result.hits:
            source_id = _source_id(hit.text)
            hits.append({
                "source_id": source_id,
                "kind": hit.citation.memory_ref.family,
                "score": hit.score,
                "matched_by": [item.value for item in hit.matched_by],
                "text": hit.text,
            })
        return {"query": query, "scope_id": self.scope_id, "hits": hits}

    async def save_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Persist resumable task state through PowerContext memory."""

        payload = {"task_id": "goalflow-213", "saved_at": datetime.now(UTC).isoformat(), **state}
        async with self._client(60) as client:
            result = await client.remember_memory(
                RememberMemoryRequest(
                    scope_id=self.scope_id,
                    kind="goalflow-213-task-state",
                    text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    reason="GoalFlow Issue 213 resumable task state",
                )
            )
        return {"task_id": payload["task_id"], "memory_id": result.memory.artifact_id, "state": payload}

    async def resume_state(self) -> dict[str, Any] | None:
        """Read the latest saved state after a module restart."""

        async with self._client(60) as client:
            result = await client.search_memory(
                SearchMemoryRequest(
                    scope_id=self.scope_id,
                    query="goalflow-213-task-state",
                    limit=10,
                )
            )
        states = []
        for hit in result.hits:
            try:
                value = json.loads(hit.text)
            except json.JSONDecodeError:
                continue
            if value.get("task_id") == "goalflow-213":
                states.append(value)
        return max(states, key=lambda item: item.get("saved_at", ""), default=None)

    def call_minimax(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        """Call the configured MiniMax OpenAI-compatible chat endpoint."""

        if not self.config.minimax_url or not self.config.minimax_api_key:
            raise RuntimeError("MINIMAX_CHAT_URL and MINIMAX_API_KEY are required for model execution")  # noqa: TRY003
        if urlsplit(self.config.minimax_url).scheme not in {"http", "https"}:
            raise ValueError("MINIMAX_CHAT_URL must use http or https")  # noqa: TRY003
        body = json.dumps(
            {
                "model": self.config.minimax_model,
                "messages": [
                    {"role": "user", "content": f"{prompt}\n\nCONTEXT:\n{json.dumps(context, ensure_ascii=False)}"}
                ],
                "temperature": 0,
            },
            ensure_ascii=False,
        ).encode()
        request = urllib.request.Request(  # noqa: S310
            self.config.minimax_url,
            data=body,
            headers={"Authorization": f"Bearer {self.config.minimax_api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))


def _source_id(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("SOURCE_ID: "):
            return line.removeprefix("SOURCE_ID: ").strip()
    return "unknown"
