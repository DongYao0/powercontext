"""Start the PowerContext Server used by the competition demo."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from pydantic import SecretStr

from powercontext.builtin.persistence.oceanbase import OceanBaseConfig
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.config import RuntimeConfig
from powercontext.server.factory import create_server_app
from powercontext.server.settings import AccessControlConfig, HttpConfig, McpConfig, ServerSettings


def _database():
    kind = os.environ.get("MINIMAX_DB_KIND", "sqlite").lower()
    if kind == "oceanbase":
        url = os.environ.get("MINIMAX_OCEANBASE_URL")
        if not url:
            raise RuntimeError("MINIMAX_OCEANBASE_URL is required for OceanBase")  # noqa: TRY003
        return OceanBaseConfig(url=SecretStr(url))
    if kind == "seekdb":
        return SeekDBConfig(path=Path(os.environ.get("MINIMAX_SEEKDB_PATH", ".powercontext/seekdb")))
    return SQLiteConfig(url=os.environ.get("MINIMAX_SQLITE_URL", "sqlite+aiosqlite:///minimax/powercontext.db"))


def main() -> None:
    app = create_server_app(
        settings=ServerSettings(
            workspace=Path.cwd(),
            database=_database(),
            http=HttpConfig(host=os.environ.get("MINIMAX_HOST", "127.0.0.1")),
            access=AccessControlConfig(mode="disabled"),
            mcp=McpConfig(enabled=False),
            runtime=RuntimeConfig(schedule_seconds=None, experience_schedule_seconds=None),
        )
    )
    uvicorn.run(app, host=os.environ.get("MINIMAX_HOST", "127.0.0.1"), port=int(os.environ.get("MINIMAX_PORT", "8000")))


if __name__ == "__main__":
    main()
