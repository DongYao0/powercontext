from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from minimax.context_module.service import ContextModule, ContextModuleConfig, _source_id
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.server.factory import create_server_app
from powercontext.server.settings import McpConfig, ServerSettings


def test_source_id_is_recoverable_from_imported_memory() -> None:
    assert _source_id("SOURCE_ID: docs/rfcs/0012.md\nSOURCE_KIND: spec\n\ntext") == "docs/rfcs/0012.md"  # noqa: S101


def test_source_id_has_safe_fallback() -> None:
    assert _source_id("unlabelled text") == "unknown"  # noqa: S101


def test_config_reads_runtime_endpoints_without_persisting_credentials(monkeypatch) -> None:
    monkeypatch.setenv("POWERCONTEXT_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("MINIMAX_CHAT_URL", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("MINIMAX_API_KEY", "placeholder")
    config = ContextModuleConfig.from_env()
    assert config.server_url == "http://127.0.0.1:8000"  # noqa: S101
    assert config.minimax_url.endswith("/chat/completions")  # noqa: S101
    assert config.minimax_api_key == "placeholder"  # noqa: S101


def test_context_module_round_trip_reuses_powercontext_state(tmp_path: Path) -> None:
    app = create_server_app(
        settings=ServerSettings(
            database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'context.db'}"),
            mcp=McpConfig(enabled=False),
        )
    )

    async def scenario() -> None:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as transport,
        ):
            config = ContextModuleConfig(server_url="http://testserver", scope_id="goalflow-213")
            module = ContextModule(config, http_client=transport)
            await module.initialize()
            await module.import_sources([
                {"source_id": "fixtures/issue-213.md", "kind": "spec", "text": "owner isolation stable sort"}
            ])
            context = await module.build_context("owner isolation")
            assert any(hit["source_id"] == "fixtures/issue-213.md" for hit in context["hits"])  # noqa: S101
            await module.save_state({"completed": ["import"], "pending": ["verify"]})

            restarted = ContextModule(config, http_client=transport)
            await restarted.initialize()
            state = await restarted.resume_state()
            assert state is not None  # noqa: S101
            assert state["completed"] == ["import"]  # noqa: S101
            assert state["pending"] == ["verify"]  # noqa: S101

    asyncio.run(scenario())
