"""用户级长期记忆生命周期服务（T17 / #145）。

这里是记忆状态变更的唯一执行者。HTTP 路由、提取作业、Agent 与来源适配器只通过本模块
的函数交换快照，不直接写 memory 表。

所有写路径都遵循同一协议：短 `Database.write()`（BEGIN IMMEDIATE）、事务内重新读取
owner 与 revision、条件检查后一次提交。外部模型、来源表和文件系统都不在事务内访问。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from goalflow.auth.service import CurrentUser
from goalflow.contracts.enums import MemoryStatus, MemoryType
from goalflow.contracts.errors import ErrorCode, GoalflowError
from goalflow.core.config import get_settings
from goalflow.db.session import Database
from goalflow.idempotency import IdempotentRequest, ResultRef, run_idempotent
from goalflow.memory.enums import MemorySourceType, SuppressionReason
from goalflow.memory.interfaces import CONFLICT_NONE, MemorySourceSnapshot, MemorySourceView
from goalflow.memory.models import ContextManifest, Memory, MemoryRevision, MemorySource, MemorySuppression
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

_BODY_SPACE = re.compile(r"\s+")
_HMAC_CONTEXT = b"goalflow-memory-v1"
_MEMORY_RESULT = "memory"


@dataclass(frozen=True, slots=True)
class MemoryView:
    """HTTP 与内部调用共用的记忆快照；正文仍只在用户可见状态下返回。"""

    id: str
    type: MemoryType
    status: MemoryStatus
    body: str
    head_revision: int
    revision: int
    conflict: str
    sources: list[MemorySourceView]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryListView:
    items: list[MemoryView]
    total: int


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> str:
    return str(uuid.uuid4())


def _normalize_body(body: str) -> str:
    """把用户可见正文归一化为稳定的比较输入，不改变存储正文。"""
    return _BODY_SPACE.sub(" ", body.strip()).casefold()


def normalized_key(memory_type: MemoryType, body: str) -> str:
    """返回同一用户下用于候选去重的内容摘要。"""
    value = f"{memory_type.value}\x00{_normalize_body(body)}".encode()
    return hashlib.sha256(value).hexdigest()


def _source_digest(snapshot: MemorySourceSnapshot) -> str:
    return snapshot.source_digest


def _hmac_secret() -> bytes:
    configured = get_settings().session_secret
    if configured is None or not configured.get_secret_value():
        raise GoalflowError(ErrorCode.INTERNAL_ERROR, "长期记忆抑制指纹密钥尚未配置")
    return configured.get_secret_value().encode()


def _digest(secret: bytes, value: str) -> str:
    return hmac.new(secret, _HMAC_CONTEXT + b"\x00" + value.encode(), hashlib.sha256).hexdigest()


def _content_hmac(owner_id: str, key: str) -> str:
    return _digest(_hmac_secret(), f"content\x00{owner_id}\x00{key}")


def _source_hmac(owner_id: str, source: MemorySourceSnapshot) -> str:
    return _digest(
        _hmac_secret(),
        "source\x00{}\x00{}\x00{}\x00{}\x00{}".format(
            owner_id,
            source.source_type.value,
            source.source_id,
            source.source_revision if source.source_revision is not None else "",
            source.source_digest,
        ),
    )


def _memory_query(session: Session, owner_id: str, memory_id: str) -> Memory:
    row = session.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner_id))
    if row is None:
        raise GoalflowError(ErrorCode.NOT_FOUND, "记忆不存在")
    return row


def _head(session: Session, memory: Memory) -> MemoryRevision:
    row = session.scalar(
        select(MemoryRevision).where(
            MemoryRevision.memory_id == memory.id,
            MemoryRevision.revision == memory.head_revision,
        )
    )
    if row is None:
        # 这是内部数据损坏，不把它伪装成用户的 404。
        raise GoalflowError(ErrorCode.INTERNAL_ERROR, "记忆当前版本不存在")
    return row


def _sources(session: Session, memory_id: str, *, owner_id: str) -> list[MemorySourceView]:
    rows = list(
        session.scalars(
            select(MemorySource)
            .where(MemorySource.memory_id == memory_id, MemorySource.owner_id == owner_id)
            .order_by(MemorySource.created_at, MemorySource.id)
        )
    )
    return [
        MemorySourceView(
            source_type=MemorySourceType(row.source_type),
            source_id=row.source_id,
            available=True,
            created_at=row.created_at,
        )
        for row in rows
    ]


def _view(session: Session, memory: Memory, *, owner_id: str) -> MemoryView:
    head = _head(session, memory)
    return MemoryView(
        id=memory.id,
        type=MemoryType(memory.type),
        status=MemoryStatus(memory.status),
        body=head.body,
        head_revision=memory.head_revision,
        revision=memory.revision,
        conflict="none",
        sources=_sources(session, memory.id, owner_id=owner_id),
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def _require_revision(memory: Memory, expected_revision: int) -> None:
    if memory.revision != expected_revision:
        raise GoalflowError(ErrorCode.REVISION_CONFLICT, "记忆已被更新，请刷新后重试")


def _require_status(memory: Memory, *allowed: MemoryStatus) -> None:
    if MemoryStatus(memory.status) not in allowed:
        allowed_text = "、".join(item.value for item in allowed)
        raise GoalflowError(
            ErrorCode.CONFIRMATION_REQUIRED,
            f"当前记忆状态为 {memory.status}，该操作只适用于 {allowed_text}",
        )


def _source_id(operation: str, owner_id: str, memory_id: str, key: str) -> str:
    """把幂等键映射成稳定 UUID，避免把最多 200 字符的 key 写入 36 字符 source_id。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"goalflow:{operation}:{owner_id}:{memory_id}:{key}"))


def _manual_source(owner_id: str, body: str, key: str) -> MemorySourceSnapshot:
    return MemorySourceSnapshot(
        source_type=MemorySourceType.USER_CONFIRMATION,
        source_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"goalflow:manual:{owner_id}:{key}")),
        source_digest=hashlib.sha256(body.encode()).hexdigest(),
    )


def _insert_source(
    session: Session,
    memory: Memory,
    revision: int,
    source: MemorySourceSnapshot,
    *,
    owner_id: str,
    now: datetime,
) -> None:
    existing = session.scalar(
        select(MemorySource.id).where(
            MemorySource.memory_id == memory.id,
            MemorySource.memory_revision == revision,
            MemorySource.source_type == source.source_type.value,
            MemorySource.source_id == source.source_id,
        )
    )
    if existing is None:
        session.add(
            MemorySource(
                id=_id(),
                memory_id=memory.id,
                memory_revision=revision,
                owner_id=owner_id,
                source_type=source.source_type.value,
                source_id=source.source_id,
                source_revision=source.source_revision,
                source_digest=_source_digest(source),
                created_at=now,
            )
        )
        session.flush()


def _insert_revision(
    session: Session,
    memory: Memory,
    *,
    body: str,
    memory_type: MemoryType,
    source: MemorySourceSnapshot,
    owner_id: str,
    now: datetime,
) -> MemoryRevision:
    revision = memory.head_revision + 1
    row = MemoryRevision(
        memory_id=memory.id,
        revision=revision,
        body=body,
        normalized_key=normalized_key(memory_type, body),
        created_at=now,
    )
    session.add(row)
    session.flush()
    _insert_source(session, memory, revision, source, owner_id=owner_id, now=now)
    memory.head_revision = revision
    memory.revision += 1
    memory.updated_at = now
    session.flush()
    return row


def _replace_fts(session: Session, memory: Memory, *, body: str | None) -> None:
    # The FTS table is intentionally not in ORM metadata; use text() so this remains true.
    from sqlalchemy import text

    session.execute(text("DELETE FROM memory_fts WHERE memory_id = :memory_id"), {"memory_id": memory.id})
    if body is not None:
        session.execute(
            text("INSERT INTO memory_fts (memory_id, revision, body) VALUES (:memory_id, :revision, :body)"),
            {"memory_id": memory.id, "revision": memory.head_revision, "body": body},
        )


def _active_suppression(
    session: Session,
    *,
    owner_id: str,
    key: str,
    source: MemorySourceSnapshot,
) -> MemorySuppression | None:
    """只抑制同一内容、同一来源指纹的再次提名。

    `content_hmac` 负责不保存正文，`source_hmac` 负责区分来源实体与其 revision/digest；
    另一个来源提出同一陈述不应被用户对旧来源的拒绝静默吞掉。
    """
    return session.scalar(
        select(MemorySuppression).where(
            MemorySuppression.owner_id == owner_id,
            MemorySuppression.content_hmac == _content_hmac(owner_id, key),
            MemorySuppression.source_hmac == _source_hmac(owner_id, source),
            MemorySuppression.revoked_at.is_(None),
        )
    )


def _upsert_suppression(
    session: Session,
    *,
    owner_id: str,
    key: str,
    source: MemorySourceSnapshot,
    reason: SuppressionReason,
    now: datetime,
) -> None:
    content = _content_hmac(owner_id, key)
    row = session.scalar(
        select(MemorySuppression).where(
            MemorySuppression.owner_id == owner_id,
            MemorySuppression.content_hmac == content,
        )
    )
    if row is None:
        session.add(
            MemorySuppression(
                id=_id(),
                owner_id=owner_id,
                content_hmac=content,
                source_hmac=_source_hmac(owner_id, source),
                reason=reason.value,
                created_at=now,
                revoked_at=None,
            )
        )
    else:
        row.source_hmac = _source_hmac(owner_id, source)
        row.reason = reason.value
        row.revoked_at = None
    session.flush()


def _create_candidate_in_session(
    session: Session,
    *,
    owner_id: str,
    memory_type: MemoryType,
    body: str,
    source: MemorySourceSnapshot,
    now: datetime,
) -> str:
    key = normalized_key(memory_type, body)
    if _active_suppression(session, owner_id=owner_id, key=key, source=source) is not None:
        raise GoalflowError(ErrorCode.CONFIRMATION_REQUIRED, "该记忆已被抑制，请先撤销抑制后重试")

    existing = session.scalar(
        select(Memory)
        .join(MemoryRevision, MemoryRevision.memory_id == Memory.id)
        .where(
            Memory.owner_id == owner_id,
            Memory.type == memory_type.value,
            MemoryRevision.normalized_key == key,
            Memory.status.in_((MemoryStatus.CANDIDATE.value, MemoryStatus.CONFIRMED.value)),
            MemoryRevision.revision == Memory.head_revision,
        )
        .order_by(Memory.created_at, Memory.id)
    )
    if existing is not None:
        _insert_source(session, existing, existing.head_revision, source, owner_id=owner_id, now=now)
        existing.updated_at = now
        session.flush()
        return existing.id

    # 相同正文归一化键之下不会自动合并不同类型；相同类型但正文不同的候选也保留为独立
    # 记忆，冲突关联留给后续候选/检索策略，不在生命周期服务里猜测业务事实。

    memory_id = _id()
    memory = Memory(
        id=memory_id,
        owner_id=owner_id,
        type=memory_type.value,
        status=MemoryStatus.CANDIDATE.value,
        head_revision=1,
        revision=0,
        created_at=now,
        updated_at=now,
    )
    session.add(memory)
    session.flush()
    revision = MemoryRevision(
        memory_id=memory_id,
        revision=1,
        body=body,
        normalized_key=key,
        created_at=now,
    )
    session.add(revision)
    session.flush()
    _insert_source(session, memory, 1, source, owner_id=owner_id, now=now)
    return memory_id


def create_candidate(
    database: Database,
    user: CurrentUser,
    *,
    memory_type: MemoryType,
    body: str,
    source: MemorySourceSnapshot,
) -> MemoryView:
    """来源模块使用的内部候选入口；永远只创建 candidate。"""
    now = _now()
    with database.write() as session:
        memory_id = _create_candidate_in_session(
            session, owner_id=user.user_id, memory_type=memory_type, body=body, source=source, now=now
        )
        memory = _memory_query(session, user.user_id, memory_id)
        return _view(session, memory, owner_id=user.user_id)


def create_extracted_candidate(
    session: Session,
    *,
    owner_id: str,
    memory_type: MemoryType,
    body: str,
    source: MemorySourceSnapshot,
    now: datetime,
) -> str | None:
    """提取作业在写事务里创建候选；命中抑制时返回 None 而不是报错。

    与 `create_candidate` 的区别只在抑制的处理：提取是后台派生过程，用户拒绝过的陈述再次被
    模型提出时应当被安静跳过，而不是让整个作业失败。其余语义（只写 candidate、相同归一化键
    复用现有记忆并追加来源）与候选创建完全一致。
    """
    key = normalized_key(memory_type, body)
    if _active_suppression(session, owner_id=owner_id, key=key, source=source) is not None:
        return None
    return _create_candidate_in_session(
        session, owner_id=owner_id, memory_type=memory_type, body=body, source=source, now=now
    )


def create_memory(
    database: Database,
    user: CurrentUser,
    *,
    memory_type: MemoryType,
    body: str,
    idempotency_key: str,
    request_body: BaseModel,
) -> MemoryView:
    now = _now()
    operation = "memory.create_candidate"
    request = IdempotentRequest.build(
        owner_id=user.user_id,
        operation=operation,
        key=idempotency_key,
        body=request_body,
    )
    source = _manual_source(user.user_id, body, idempotency_key)
    with database.write() as session:
        outcome = run_idempotent(
            session,
            request,
            lambda: (
                ResultRef(
                    _MEMORY_RESULT,
                    _create_candidate_in_session(
                        session,
                        owner_id=user.user_id,
                        memory_type=memory_type,
                        body=body,
                        source=source,
                        now=now,
                    ),
                ),
                201,
            ),
            now=now,
        )
        return _view(session, _memory_query(session, user.user_id, outcome.result.id), owner_id=user.user_id)


def get_memory(database: Database, user: CurrentUser, memory_id: str) -> MemoryView:
    with database.read() as session:
        return _view(session, _memory_query(session, user.user_id, memory_id), owner_id=user.user_id)


def list_memories(
    database: Database,
    user: CurrentUser,
    *,
    status: MemoryStatus,
    memory_type: MemoryType | None,
    limit: int,
) -> MemoryListView:
    with database.read() as session:
        conditions = [Memory.owner_id == user.user_id, Memory.status == status.value]
        if memory_type is not None:
            conditions.append(Memory.type == memory_type.value)
        total = session.scalar(select(func.count()).select_from(Memory).where(*conditions)) or 0
        rows = list(
            session.scalars(
                select(Memory).where(*conditions).order_by(Memory.updated_at.desc(), Memory.id).limit(limit)
            )
        )
        return MemoryListView(
            items=[_view(session, row, owner_id=user.user_id) for row in rows],
            total=int(total),
        )


def _run_memory_write(
    database: Database,
    user: CurrentUser,
    *,
    memory_id: str,
    operation: str,
    idempotency_key: str,
    request_body: BaseModel,
    action: Callable[[Session, Memory, datetime], None],
    status_code: int = 200,
) -> MemoryView:
    now = _now()
    request = IdempotentRequest.build(
        owner_id=user.user_id,
        operation=operation,
        key=idempotency_key,
        body=request_body,
        path_params={"memory_id": memory_id},
    )
    with database.write() as session:

        def execute() -> tuple[ResultRef, int]:
            action(session, _memory_query(session, user.user_id, memory_id), now)
            return ResultRef(_MEMORY_RESULT, memory_id), status_code

        outcome = run_idempotent(session, request, execute, now=now)
        return _view(session, _memory_query(session, user.user_id, outcome.result.id), owner_id=user.user_id)


def confirm_memory(
    database: Database,
    user: CurrentUser,
    memory_id: str,
    *,
    expected_revision: int,
    idempotency_key: str,
    request_body: BaseModel,
) -> MemoryView:
    def action(session: Session, memory: Memory, now: datetime) -> None:
        _require_revision(memory, expected_revision)
        _require_status(memory, MemoryStatus.CANDIDATE)
        source = MemorySourceSnapshot(
            source_type=MemorySourceType.USER_CONFIRMATION,
            source_id=_source_id("confirm", user.user_id, memory.id, idempotency_key),
            source_digest=hashlib.sha256(f"confirm:{memory.id}:{memory.revision}".encode()).hexdigest(),
        )
        memory.status = MemoryStatus.CONFIRMED.value
        memory.revision += 1
        memory.updated_at = now
        _insert_source(session, memory, memory.head_revision, source, owner_id=user.user_id, now=now)
        _replace_fts(session, memory, body=_head(session, memory).body)
        session.flush()

    return _run_memory_write(
        database,
        user,
        memory_id=memory_id,
        operation="memory.confirm",
        idempotency_key=idempotency_key,
        request_body=request_body,
        action=action,
    )


def edit_memory(
    database: Database,
    user: CurrentUser,
    memory_id: str,
    *,
    body: str,
    expected_revision: int,
    idempotency_key: str,
    request_body: BaseModel,
) -> MemoryView:
    def action(session: Session, memory: Memory, now: datetime) -> None:
        _require_revision(memory, expected_revision)
        _require_status(memory, MemoryStatus.CANDIDATE, MemoryStatus.CONFIRMED)
        source = MemorySourceSnapshot(
            source_type=MemorySourceType.USER_CONFIRMATION,
            source_id=_source_id("edit", user.user_id, memory.id, idempotency_key),
            source_digest=hashlib.sha256(body.encode()).hexdigest(),
        )
        _insert_revision(
            session,
            memory,
            body=body,
            memory_type=MemoryType(memory.type),
            source=source,
            owner_id=user.user_id,
            now=now,
        )
        if memory.status == MemoryStatus.CONFIRMED.value:
            _replace_fts(session, memory, body=body)

    return _run_memory_write(
        database,
        user,
        memory_id=memory_id,
        operation="memory.edit",
        idempotency_key=idempotency_key,
        request_body=request_body,
        action=action,
    )


def reject_memory(
    database: Database,
    user: CurrentUser,
    memory_id: str,
    *,
    expected_revision: int,
    idempotency_key: str,
    request_body: BaseModel,
) -> MemoryView:
    def action(session: Session, memory: Memory, now: datetime) -> None:
        _require_revision(memory, expected_revision)
        _require_status(memory, MemoryStatus.CANDIDATE)
        source_rows = list(session.scalars(select(MemorySource).where(MemorySource.memory_id == memory.id)))
        current = _head(session, memory)
        source = (
            MemorySourceSnapshot(
                source_type=MemorySourceType(source_rows[0].source_type),
                source_id=source_rows[0].source_id,
                source_digest=source_rows[0].source_digest,
                source_revision=source_rows[0].source_revision,
            )
            if source_rows
            else MemorySourceSnapshot(
                source_type=MemorySourceType.USER_CONFIRMATION,
                source_id=memory.id,
                source_digest=hashlib.sha256(current.body.encode()).hexdigest(),
            )
        )
        _upsert_suppression(
            session,
            owner_id=user.user_id,
            key=current.normalized_key,
            source=source,
            reason=SuppressionReason.REJECTED,
            now=now,
        )
        memory.status = MemoryStatus.REJECTED.value
        memory.revision += 1
        memory.updated_at = now
        _replace_fts(session, memory, body=None)
        session.flush()

    return _run_memory_write(
        database,
        user,
        memory_id=memory_id,
        operation="memory.reject",
        idempotency_key=idempotency_key,
        request_body=request_body,
        action=action,
    )


def invalidate_memory(
    database: Database,
    user: CurrentUser,
    memory_id: str,
    *,
    expected_revision: int,
    idempotency_key: str,
    request_body: BaseModel,
) -> MemoryView:
    def action(session: Session, memory: Memory, now: datetime) -> None:
        _require_revision(memory, expected_revision)
        _require_status(memory, MemoryStatus.CANDIDATE, MemoryStatus.CONFIRMED)
        current = _head(session, memory)
        source_rows = list(session.scalars(select(MemorySource).where(MemorySource.memory_id == memory.id)))
        source = (
            MemorySourceSnapshot(
                source_type=MemorySourceType(source_rows[0].source_type),
                source_id=source_rows[0].source_id,
                source_digest=source_rows[0].source_digest,
                source_revision=source_rows[0].source_revision,
            )
            if source_rows
            else MemorySourceSnapshot(
                source_type=MemorySourceType.USER_CONFIRMATION,
                source_id=memory.id,
                source_digest=hashlib.sha256(current.body.encode()).hexdigest(),
            )
        )
        _upsert_suppression(
            session,
            owner_id=user.user_id,
            key=current.normalized_key,
            source=source,
            reason=SuppressionReason.INVALIDATED,
            now=now,
        )
        memory.status = MemoryStatus.INVALIDATED.value
        memory.revision += 1
        memory.updated_at = now
        _replace_fts(session, memory, body=None)
        session.flush()

    return _run_memory_write(
        database,
        user,
        memory_id=memory_id,
        operation="memory.invalidate",
        idempotency_key=idempotency_key,
        request_body=request_body,
        action=action,
    )


def revoke_suppression(
    database: Database,
    user: CurrentUser,
    memory_id: str,
    *,
    idempotency_key: str,
    request_body: BaseModel,
) -> MemoryView:
    def action(session: Session, memory: Memory, now: datetime) -> None:
        current = _head(session, memory)
        row = session.scalar(
            select(MemorySuppression).where(
                MemorySuppression.owner_id == user.user_id,
                MemorySuppression.content_hmac == _content_hmac(user.user_id, current.normalized_key),
            )
        )
        if row is not None:
            row.revoked_at = now
            session.flush()

    return _run_memory_write(
        database,
        user,
        memory_id=memory_id,
        operation="memory.revoke_suppression",
        idempotency_key=idempotency_key,
        request_body=request_body,
        action=action,
    )


def invalidate_source(
    database: Database,
    *,
    owner_id: str,
    source: MemorySourceSnapshot,
) -> int:
    """来源模块删除实体时调用；只处理该来源，不读取来源模块的内部表。

    删除来源引用后，只有没有任何剩余来源的 candidate 才会自动 invalidated；confirmed
    记忆若仍有用户确认来源则保留。返回发生状态变化的记忆数。
    """
    now = _now()
    changed = 0
    with database.write() as session:
        rows = list(
            session.scalars(
                select(MemorySource).where(
                    MemorySource.owner_id == owner_id,
                    MemorySource.source_type == source.source_type.value,
                    MemorySource.source_id == source.source_id,
                )
            )
        )
        memory_ids = {row.memory_id for row in rows}
        for row in rows:
            session.delete(row)
        session.flush()
        for memory_id in memory_ids:
            memory = _memory_query(session, owner_id, memory_id)
            remaining = session.scalar(
                select(func.count()).select_from(MemorySource).where(MemorySource.memory_id == memory.id)
            )
            if remaining == 0 and memory.status == MemoryStatus.CANDIDATE.value:
                current = _head(session, memory)
                _upsert_suppression(
                    session,
                    owner_id=owner_id,
                    key=current.normalized_key,
                    source=source,
                    reason=SuppressionReason.INVALIDATED,
                    now=now,
                )
                memory.status = MemoryStatus.INVALIDATED.value
                memory.revision += 1
                memory.updated_at = now
                _replace_fts(session, memory, body=None)
                changed += 1
        return changed


# ---------- 上下文清单只读查询（#213） ----------


@dataclass(frozen=True, slots=True)
class ContextManifestEntryView:
    """清单里的一条注入记录：只含引用与预算，不含正文。

    字段与 `goalflow.memory.interfaces.ContextManifestEntry` 一致——那是写入侧形状，
    这里是同一份记录的只读视图。
    """

    layer: str
    entry_type: str
    entity_id: str
    revision: int | None
    allocated_budget: int
    used_budget: int
    truncated_reason: str | None
    conflict: str


@dataclass(frozen=True, slots=True)
class ContextManifestView:
    """一次模型调用实际注入的上下文清单（RFC 0012 第 7 节）。

    **不含正文**：条目只记实体引用、revision、来源层、分配与实际预算、截断原因与
    冲突状态。`scope` 不在这里对外：它当前恒等于 owner，暴露等于重复暴露归属信息。
    """

    id: str
    job_id: str | None
    step: str
    actor: str
    strategy_revision: str
    retrieval_mode: str
    created_at: datetime
    entries: list[ContextManifestEntryView]


@dataclass(frozen=True, slots=True)
class ContextManifestListView:
    items: list[ContextManifestView]
    total: int


def _manifest_entries(raw: str) -> list[ContextManifestEntryView]:
    """把存储的 JSON 条目读成视图。

    `entries` 由 `goalflow.memory.context.manifest_draft` 写入，形状固定。这里的兜底
    只针对历史数据损坏：读不动的条目跳过，不让整个查询失败——清单是可观测性数据，
    不该因为一条脏记录就把整次诊断打断。
    """
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    entries: list[ContextManifestEntryView] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        revision = item.get("revision")
        truncated_reason = item.get("truncated_reason")
        entries.append(
            ContextManifestEntryView(
                layer=str(item.get("layer", "")),
                entry_type=str(item.get("entry_type", "")),
                entity_id=str(item.get("entity_id", "")),
                revision=int(revision) if isinstance(revision, int) else None,
                allocated_budget=int(item.get("allocated_budget", 0)),
                used_budget=int(item.get("used_budget", 0)),
                truncated_reason=truncated_reason if isinstance(truncated_reason, str) else None,
                conflict=str(item.get("conflict", CONFLICT_NONE)),
            )
        )
    return entries


def _manifest_view(row: ContextManifest) -> ContextManifestView:
    return ContextManifestView(
        id=row.id,
        job_id=row.job_id,
        step=row.step,
        actor=row.actor,
        strategy_revision=row.strategy_revision,
        retrieval_mode=row.retrieval_mode,
        created_at=row.created_at,
        entries=_manifest_entries(row.entries),
    )


def list_context_manifests(
    database: Database,
    user: CurrentUser,
    *,
    job_id: str | None,
    step: str | None,
    limit: int,
) -> ContextManifestListView:
    """列出当前用户的上下文清单（#213）。

    owner 只来自服务端会话，不接受调用方传入——它是服务端绑定的事实，不是筛选条件。
    查询维度是 owner + job_id + step；排序固定 `created_at ASC, id ASC`，同一份数据
    重复查询结果一致。
    """
    with database.read() as session:
        conditions = [ContextManifest.owner_id == user.user_id]
        if job_id is not None:
            conditions.append(ContextManifest.job_id == job_id)
        if step is not None:
            conditions.append(ContextManifest.step == step)
        total = session.scalar(select(func.count()).select_from(ContextManifest).where(*conditions)) or 0
        rows = list(
            session.scalars(
                select(ContextManifest)
                .where(*conditions)
                .order_by(ContextManifest.created_at.asc(), ContextManifest.id.asc())
                .limit(limit)
            )
        )
        return ContextManifestListView(
            items=[_manifest_view(row) for row in rows],
            total=int(total),
        )


def get_context_manifest(database: Database, user: CurrentUser, manifest_id: str) -> ContextManifestView:
    """读取一条上下文清单。

    跨用户与不存在统一返回 NOT_FOUND，响应无法区分二者——否则调用方能从响应差异里
    推断某个清单 ID 是否存在（与记忆详情同一约定）。
    """
    with database.read() as session:
        row = session.scalar(
            select(ContextManifest).where(
                ContextManifest.id == manifest_id,
                ContextManifest.owner_id == user.user_id,
            )
        )
        if row is None:
            raise GoalflowError(ErrorCode.NOT_FOUND, "上下文清单不存在")
        return _manifest_view(row)
