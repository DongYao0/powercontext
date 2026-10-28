"""FastAPI 应用装配。

本函数不读配置、不配日志，保证 `goalflow.tools.export_openapi` 在任何环境下
都能导出同一份文档。进程级初始化在 goalflow.api.main。
"""

from fastapi import FastAPI
from goalflow.api.errors import register_exception_handlers
from goalflow.api.middleware import RequestIdMiddleware
from goalflow.api.routes import (
    auth,
    capability_configs,
    checkins,
    context_manifests,
    conversations,
    goal_links,
    goals,
    health,
    jobs,
    memory,
    model_configs,
    scheduling,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="GoalFlow API",
        version="0.1.0",
        description="GoalFlow 的 HTTP 契约事实源。本文档由 scripts/api-generate.sh 导出，禁止手工编辑。",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )

    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(jobs.router)
    app.include_router(goals.router)
    app.include_router(conversations.router)
    app.include_router(scheduling.router)
    app.include_router(goal_links.router)
    app.include_router(capability_configs.router)
    app.include_router(model_configs.router)
    app.include_router(checkins.router)
    app.include_router(memory.router)
    app.include_router(context_manifests.router)

    return app
