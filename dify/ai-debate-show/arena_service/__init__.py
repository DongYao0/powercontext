"""《再说一遍？》节目内容核心层。

对外只暴露领域模型、异常与两个公共函数；内部辅助函数不对外导出。
"""

from .app import (
    ArenaApplication,
    ArenaApplicationError,
    ArenaSession,
    GameNotFoundError,
    MemoryUnavailableError,
)
from .content import (
    ContentValidationError,
    NoMatchingCardError,
    load_content_catalog,
    select_rebuttal_card,
)
from .game import (
    GAME_ACTIONS,
    GameFinishedError,
    GameInputError,
    GameState,
    RoundPlan,
    advance_round,
    start_game,
)
from .game_memory import (
    ALLOWED_MEMORY_KINDS,
    MEMORY_TEXT_MAX_UTF8_BYTES,
    REASON_MAX_LENGTH,
    SCOPE_ID_MAX_LENGTH,
    SOURCE_ID_MAX_LENGTH,
    GameMemoryEvent,
    GameMemoryRecorder,
    GameMemoryValidationError,
)
from .models import CardSelection, Character, ContentCatalog, RebuttalCard, Topic
from .powercontext import (
    PowerContextClient,
    PowerContextError,
    PowerContextWriteError,
    PreparedContext,
)

__all__ = [
    "ALLOWED_MEMORY_KINDS",
    "GAME_ACTIONS",
    "MEMORY_TEXT_MAX_UTF8_BYTES",
    "REASON_MAX_LENGTH",
    "SCOPE_ID_MAX_LENGTH",
    "SOURCE_ID_MAX_LENGTH",
    "ArenaApplication",
    "ArenaApplicationError",
    "ArenaSession",
    "CardSelection",
    "Character",
    "ContentCatalog",
    "ContentValidationError",
    "GameFinishedError",
    "GameInputError",
    "GameMemoryEvent",
    "GameMemoryRecorder",
    "GameMemoryValidationError",
    "GameNotFoundError",
    "GameState",
    "MemoryUnavailableError",
    "NoMatchingCardError",
    "PowerContextClient",
    "PowerContextError",
    "PowerContextWriteError",
    "PreparedContext",
    "RebuttalCard",
    "RoundPlan",
    "Topic",
    "advance_round",
    "load_content_catalog",
    "select_rebuttal_card",
    "start_game",
]
