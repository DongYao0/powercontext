"""上下文清单只读查询入口（#213，RFC 0012 第 7 节）。

清单回答「本次模型调用实际注入了什么、来自哪里、为何被截断或排除」。**只读**：两条
GET，不带幂等键，也不改任何状态。

三条边界：

1. **owner 由服务端会话绑定**，不接受请求参数传入。跨用户与不存在的记录统一返回 404，
   响应无法区分二者——否则调用方能从响应差异里推断某个清单 ID 是否存在。
2. **只含引用与预算，不含正文**。记忆正文与检索正文都不在响应里；条目只有实体 ID、
   revision、来源层、预算、截断原因与冲突状态。
3. **不暴露 `scope`**：该列当前恒等于 owner，暴露等于重复暴露归属信息。

查询维度是 owner + job_id + step；排序固定 `created_at ASC, id ASC`，重复查询结果一致。
"""

from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Path, Query
from goalflow.api.dependencies import CurrentUserDep, DatabaseDep
from goalflow.contracts.http import ErrorResponse
from goalflow.memory import service
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/context-manifests", tags=["context-manifests"])

_ERROR_DESCRIPTIONS: Final = {
    401: "未登录或会话失效",
    403: "请求来源不受信任",
    404: "上下文清单不存在，或不属于当前用户",
    422: "请求参数校验未通过",
}

_MAX_PAGE_SIZE: Final = 100
_DEFAULT_PAGE_SIZE: Final = 20


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse, "description": _ERROR_DESCRIPTIONS[code]} for code in codes}


ManifestIdPath = Annotated[str, Path(max_length=36, description="上下文清单 ID")]


class ContextManifestEntryResponse(BaseModel):
    """清单里的一条注入记录。只含引用与预算，不含正文。"""

    layer: str = Field(description="来源层，例如 L3_confirmed_memory")
    entry_type: str = Field(description="条目类型，例如 memory / evidence / context")
    entity_id: str = Field(description="来源实体 ID；据此可回溯到具体条目")
    revision: int | None = Field(default=None, description="来源实体的版本；来源没有版本时为空")
    allocated_budget: int = Field(ge=0, description="该条目所属层分配的预算（字符）")
    used_budget: int = Field(ge=0, description="该条目实际占用的预算（字符）")
    truncated_reason: str | None = Field(
        default=None,
        description="未完整注入的原因，例如 layer_budget / conflict；完整注入时为空",
    )
    conflict: str = Field(
        default="none",
        description="与业务事实的冲突状态；非 none 时该条目不注入正文",
    )


class ContextManifestResponse(BaseModel):
    """一次模型调用实际注入的上下文清单。"""

    id: str
    job_id: str | None = Field(default=None, description="绑定的作业 ID；没有绑定时为空")
    step: str = Field(description="装配发生的步骤，例如 task_assistance")
    actor: str = Field(description="记录者，例如 job")
    strategy_revision: str = Field(description="装配策略版本；用它对账当时的注入行为")
    retrieval_mode: str = Field(description="本次装配实际使用的检索通道")
    created_at: datetime
    entries: list[ContextManifestEntryResponse] = Field(
        default_factory=list,
        description="实际注入的条目。装配了但没有注入任何条目时为空数组",
    )


class ContextManifestListResponse(BaseModel):
    items: list[ContextManifestResponse]
    total: int = Field(ge=0, description="满足筛选条件的清单总数")


def _entry_response(entry: service.ContextManifestEntryView) -> ContextManifestEntryResponse:
    return ContextManifestEntryResponse(
        layer=entry.layer,
        entry_type=entry.entry_type,
        entity_id=entry.entity_id,
        revision=entry.revision,
        allocated_budget=entry.allocated_budget,
        used_budget=entry.used_budget,
        truncated_reason=entry.truncated_reason,
        conflict=entry.conflict,
    )


def _manifest_response(view: service.ContextManifestView) -> ContextManifestResponse:
    return ContextManifestResponse(
        id=view.id,
        job_id=view.job_id,
        step=view.step,
        actor=view.actor,
        strategy_revision=view.strategy_revision,
        retrieval_mode=view.retrieval_mode,
        created_at=view.created_at,
        entries=[_entry_response(entry) for entry in view.entries],
    )


@router.get(
    "",
    summary="列出上下文清单",
    description=(
        "列出当前用户的上下文清单。owner 取自服务端会话，不接受请求参数传入；"
        "可用 job_id 与 step 过滤。结果按创建时间稳定排序，重复查询结果一致。"
    ),
    responses=_errors(401, 422),
)
def list_context_manifests(
    user: CurrentUserDep,
    db: DatabaseDep,
    job_id: Annotated[str | None, Query(max_length=36, description="按绑定的作业 ID 过滤")] = None,
    step: Annotated[str | None, Query(max_length=64, description="按装配步骤过滤")] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
) -> ContextManifestListResponse:
    view = service.list_context_manifests(db, user, job_id=job_id, step=step, limit=limit)
    return ContextManifestListResponse(
        items=[_manifest_response(item) for item in view.items],
        total=view.total,
    )


@router.get(
    "/{manifest_id}",
    summary="读取上下文清单",
    description=(
        "读取一次装配的上下文清单：实际注入的条目、来源引用、预算、截断原因与策略版本。"
        "跨用户与不存在的 ID 统一返回 404。"
    ),
    responses=_errors(401, 404),
)
def get_context_manifest(
    manifest_id: ManifestIdPath,
    user: CurrentUserDep,
    db: DatabaseDep,
) -> ContextManifestResponse:
    return _manifest_response(service.get_context_manifest(db, user, manifest_id))
