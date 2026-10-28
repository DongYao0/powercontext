"""上下文清单只读查询入口的目标测试（Issue #213）。

这些用例是**先于实现**写的：它们钉住 HTTP 契约的形状与行为，实现尚未存在时它们必须失败，
且失败原因必须精确落在「查询入口尚未实现」上——不能是导入错误、依赖缺失、数据库起不来或
装置出错。

为此有两条硬约束：

1. **只 import 现存的符号。** 待实现的响应模型、服务函数一律不 import，改用原始 JSON 断言。
   否则失败会变成 pytest 收集期的 ImportError，掩盖真正的问题。
2. **只走真实 HTTP 入口。** 全部用例经 TestClient 打真实路由：路由匹配、依赖注入、
   会话 Cookie、全局异常处理器都参与。直接调用待实现的函数会让「入口是否存在」这个问题
   从根上消失——而这正是 #213 的核心。

播种用的 manifest 走**生产同一条链路**：`goalflow.memory.context` 的 L3 适配器 →
`assemble_context` → `manifest_draft` → `persist_manifest`。因此行里的内容与真实作业写入的
一致，不需要在测试里手抄一份 manifest JSON 格式。

参考：`backend/tests/memory/conftest.py` 提供 app / client / authed_client 装置；
`backend/tests/memory/test_memory_contract.py` 是同目录的契约测试范式。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from goalflow.agent.assembly.context import ContextLayer, ContextRecipe, assemble_context
from goalflow.agent.memory_context import manifest_strategy_revision
from goalflow.agent.node_blueprints import TASK_ASSISTANCE
from goalflow.contracts.enums import MemoryStatus, MemoryType
from goalflow.db.session import Database, get_database
from goalflow.memory.context import (
    L3_STRATEGY_REVISION,
    L4_STRATEGY_REVISION,
    MemoryCollection,
    l3_layer_snapshots,
    manifest_draft,
    persist_manifest,
)
from goalflow.memory.enums import RetrievalMode
from goalflow.memory.interfaces import CONFLICT_NONE, MemorySnapshot
from sqlalchemy import text

# 查询入口的路径与形状。实现方照此落地即可让本文件转绿。
LIST_PATH = "/api/context-manifests"
DETAIL_PATH = "/api/context-manifests/{manifest_id}"

# 响应体里允许出现的键。出现别的键 = 契约漂移（尤其是正文类字段）。
ITEM_KEYS = {
    "id",
    "job_id",
    "step",
    "actor",
    "strategy_revision",
    "retrieval_mode",
    "created_at",
    "entries",
}
ENTRY_KEYS = {
    "layer",
    "entry_type",
    "entity_id",
    "revision",
    "allocated_budget",
    "used_budget",
    "truncated_reason",
    "conflict",
}

# 正文泄漏探针：它出现在记忆正文里，但绝不该出现在 manifest 的任何响应中。
BODY_MARKER = "上下文清单正文泄漏探针-MARKER-213"

# 出厂配方给 L3 的字符预算（ContextRecipe.default()）。
L3_BUDGET = ContextRecipe.default().max_chars(ContextLayer.L3_CONFIRMED_MEMORY) or 0


def _app_database(app: FastAPI) -> Database:
    """取出路由实际使用的库。

    app 夹具把 get_database 覆盖成自己的库文件，与 database 夹具那份**不是同一个**。
    播种必须落到路由能读到的那一份，否则查询会「查不到自己刚写的数据」。
    """
    override = app.dependency_overrides.get(get_database)
    assert override is not None, "app 夹具未覆盖 get_database，装置不对"
    return override()


def _owner_id(client: TestClient) -> str:
    """当前登录用户的 owner_id。经会话接口取，顺带验证认证链路真的通。"""
    response = client.get("/api/auth/session")
    assert response.status_code == 200, response.text
    return str(response.json()["user"]["id"])


def _insert_other_user(database: Database) -> str:
    """另一个 owner 的账号行。跨账号隔离用例需要一条真实存在的他人记录。"""
    other_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat(timespec="microseconds")
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, account_identifier, role, status, timezone, revision, created_at, updated_at)"
                " VALUES (:id, :account, 'user', 'active', 'UTC', 0, :now, :now)"
            ),
            {
                "id": other_id,
                "account": f"other-{uuid.uuid4()}@local.dev",
                "now": now,
            },
        )
    return other_id


def _insert_job(database: Database, owner_id: str) -> str:
    """一条真实作业行。

    context_manifests.job_id 对 jobs.id 有外键，查询又按 job_id 过滤，
    所以过滤器用例必须有一行真作业，而不是一个悬空 ID。
    """
    job_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat(timespec="microseconds")
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO jobs (id, owner_id, kind, dedupe_key, input_refs_json, status, attempts, revision,"
                " created_at, updated_at)"
                " VALUES (:id, :owner, 'task_assistance', :dedupe, :refs, 'succeeded', 0, 0, :now, :now)"
            ),
            {
                "id": job_id,
                "owner": owner_id,
                "dedupe": f"gf213-{uuid.uuid4()}",
                "refs": "{}",
                "now": now,
            },
        )
    return job_id


def _memory_snapshot(memory_id: str, owner_id: str, body: str, *, revision: int = 2) -> MemorySnapshot:
    """一条已确认、无冲突的长期记忆快照。"""
    return MemorySnapshot(
        memory_id=memory_id,
        owner_id=owner_id,
        revision=revision,
        type=MemoryType.STABLE_FACT,
        status=MemoryStatus.CONFIRMED,
        body=body,
        conflict=CONFLICT_NONE,
    )


def _seed_manifest(
    database: Database,
    owner_id: str,
    *,
    job_id: str | None,
    step: str,
    snapshots: tuple[MemorySnapshot, ...],
    strategy_revision: str = L3_STRATEGY_REVISION,
) -> str:
    """按生产链路播种一条 manifest，返回它的 id。

    `persist_manifest` 吞掉写入异常（只记一条脱敏日志），所以播种后必须读回确认；
    否则一次播种失败会伪装成「查询查不到」，把装置问题误报成契约问题。

    返回值用「新增行的 id」而不是「按 step 查第一条」：同一个 step 可能播多条
    （排序用例就是），按 step 取第一条会拿到别人的行。
    """
    before = _manifest_ids(database, owner_id)
    collection = MemoryCollection(snapshots=snapshots, retrieval_mode=RetrievalMode.FTS_ONLY)
    prepared = assemble_context(ContextRecipe.default(), l3_layer_snapshots(collection))
    draft = manifest_draft(
        step=step,
        scope=owner_id,
        prepared=prepared,
        collection=collection,
        allocated_budget=L3_BUDGET,
        strategy_revision=strategy_revision,
    )
    persist_manifest(database, draft, job_id=job_id)

    created = _manifest_ids(database, owner_id) - before
    assert len(created) == 1, f"播种失败：新增了 {len(created)} 行，期望 1 行"
    return created.pop()


def _manifest_ids(database: Database, owner_id: str) -> set[str]:
    """某个 owner 名下当前已有的 manifest id。"""
    with database.read() as session:
        rows = session.execute(
            text("SELECT id FROM context_manifests WHERE owner_id = :owner"),
            {"owner": owner_id},
        ).mappings()
    return {str(row["id"]) for row in rows}


def _set_created_at(database: Database, manifest_id: str, moment: datetime) -> None:
    """把 manifest 的创建时间改成指定值。

    生产写入总是取当前时刻，两次写入几乎必然落在不同微秒上；但排序用例要断言的是
    「按创建时间排」而不是「按插入顺序排」，必须把时间钉死才有确定性。
    """
    with database.write() as session:
        session.execute(
            text("UPDATE context_manifests SET created_at = :at WHERE id = :id"),
            {"at": moment.isoformat(timespec="microseconds"), "id": manifest_id},
        )


def _assert_project_error(response, *, code: str = "NOT_FOUND") -> None:
    """断言是项目约定的资源错误，而不是「路由没注册」的默认 404。

    端点未注册时 FastAPI 抛 StarletteHTTPException，全局处理器也会把它渲染成
    `{"code": "NOT_FOUND", ...}`（见 api/errors.py::_handle_http_exception）——
    **状态码和错误码都一样**，唯一差别是 message 恰好是 FastAPI 默认的 "Not Found"。
    所以只断言状态码会把「没实现」判成「实现了且行为正确」；这里额外盯住 message，
    让「端点不存在」与「记录不存在」在断言上可区分。
    """
    body = response.json()
    assert body.get("code") == code, f"错误体不符合项目约定：{body}"
    assert "request_id" in body, f"错误体缺少 request_id：{body}"
    assert "detail" not in body, f"返回的是 FastAPI 默认错误体而不是项目错误体：{body}"
    assert body.get("message") != "Not Found", (
        "返回的是未注册路由的默认 404，而不是端点自己的资源错误——查询入口尚未实现"
    )


def test_list_context_manifests_returns_the_owner_manifest(app: FastAPI, authed_client: TestClient) -> None:
    """列表入口能查到自己 owner 名下的 manifest，并带回元数据与条目。"""
    database = _app_database(app)
    owner_id = _owner_id(authed_client)
    job_id = _insert_job(database, owner_id)
    manifest_id = _seed_manifest(
        database,
        owner_id,
        job_id=job_id,
        step="task_assistance",
        snapshots=(_memory_snapshot("mem-1", owner_id, BODY_MARKER),),
    )

    response = authed_client.get(LIST_PATH)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"items", "total"}, payload
    assert payload["total"] == 1, payload
    item = payload["items"][0]
    assert set(item) == ITEM_KEYS, item
    assert item["id"] == manifest_id
    assert item["job_id"] == job_id
    assert item["step"] == "task_assistance"
    assert item["actor"] == "job"
    assert item["strategy_revision"] == L3_STRATEGY_REVISION
    assert item["retrieval_mode"] == RetrievalMode.FTS_ONLY.value
    assert item["created_at"]


def test_context_manifest_entries_expose_budget_truncation_and_reference_without_bodies(
    app: FastAPI, authed_client: TestClient
) -> None:
    """条目带层级、来源引用、revision、预算与截断原因，且不携带任何正文。"""
    database = _app_database(app)
    owner_id = _owner_id(authed_client)
    job_id = _insert_job(database, owner_id)
    _seed_manifest(
        database,
        owner_id,
        job_id=job_id,
        step="task_assistance",
        snapshots=(_memory_snapshot("mem-1", owner_id, BODY_MARKER, revision=7),),
    )

    response = authed_client.get(LIST_PATH)

    assert response.status_code == 200, response.text
    entries = response.json()["items"][0]["entries"]
    assert len(entries) == 1, entries
    entry = entries[0]
    assert set(entry) == ENTRY_KEYS, entry
    assert entry["layer"] == ContextLayer.L3_CONFIRMED_MEMORY.value
    assert entry["entry_type"] == "memory"
    assert entry["entity_id"] == "mem-1"
    assert entry["revision"] == 7
    assert entry["allocated_budget"] == L3_BUDGET
    assert entry["used_budget"] > 0
    assert entry["truncated_reason"] is None
    assert entry["conflict"] == CONFLICT_NONE
    assert BODY_MARKER not in response.text, "响应里出现了记忆正文"


def test_over_budget_layer_records_the_truncated_entry(app: FastAPI, authed_client: TestClient) -> None:
    """L3 超预算时，被截断的条目也要出现在清单里，并带截断原因。"""
    database = _app_database(app)
    owner_id = _owner_id(authed_client)
    job_id = _insert_job(database, owner_id)
    # 第一条装满 L3 预算，第二条只剩尾部额度：被截断。
    _seed_manifest(
        database,
        owner_id,
        job_id=job_id,
        step="task_assistance",
        snapshots=(
            _memory_snapshot("mem-full", owner_id, "甲" * 1500),
            _memory_snapshot("mem-cut", owner_id, "乙" * 1500),
        ),
    )

    response = authed_client.get(LIST_PATH)

    assert response.status_code == 200, response.text
    entries = response.json()["items"][0]["entries"]
    assert len(entries) == 2, entries
    injected, truncated = entries
    assert injected["entity_id"] == "mem-full"
    assert injected["truncated_reason"] is None
    assert truncated["entity_id"] == "mem-cut"
    assert truncated["truncated_reason"] == "layer_budget"
    assert truncated["used_budget"] < L3_BUDGET


def test_get_context_manifest_returns_the_manifest_with_an_empty_entry_list(
    app: FastAPI, authed_client: TestClient
) -> None:
    """存在但条目为空的 manifest 返回 200 与空列表，不当成缺失记录。

    注意这是**防御性**契约：生产的 `persist_step_manifest` 在没有任何内容时会直接
    return，不写空行（见 agent/memory_context.py）。所以这一行由本用例经
    `persist_manifest` 显式播种，代表「库里存在但条目为空」这一状态——读路径必须
    把它当成有效记录返回，而不是当成查无此物。
    """
    database = _app_database(app)
    owner_id = _owner_id(authed_client)
    job_id = _insert_job(database, owner_id)
    manifest_id = _seed_manifest(
        database,
        owner_id,
        job_id=job_id,
        step="task_assistance",
        snapshots=(),
    )

    response = authed_client.get(DETAIL_PATH.format(manifest_id=manifest_id))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == ITEM_KEYS, payload
    assert payload["id"] == manifest_id
    assert payload["entries"] == [], payload


def test_list_context_manifests_returns_an_empty_list_when_nothing_is_recorded(
    app: FastAPI, authed_client: TestClient
) -> None:
    """名下没有任何 manifest 时，列表返回 200 与空列表，而不是 404。"""
    response = authed_client.get(LIST_PATH)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"items", "total"}, payload
    assert payload["items"] == [], payload
    assert payload["total"] == 0, payload


def test_get_context_manifest_hides_another_owners_manifest(app: FastAPI, authed_client: TestClient) -> None:
    """跨 owner 访问按「不存在」处理：详情 404，列表也不出现别人的记录。"""
    database = _app_database(app)
    owner_id = _owner_id(authed_client)
    other_id = _insert_other_user(database)
    other_job_id = _insert_job(database, other_id)
    other_manifest_id = _seed_manifest(
        database,
        other_id,
        job_id=other_job_id,
        step="task_assistance",
        snapshots=(_memory_snapshot("mem-other", other_id, "别人的记忆"),),
    )
    own_job_id = _insert_job(database, owner_id)
    own_manifest_id = _seed_manifest(
        database,
        owner_id,
        job_id=own_job_id,
        step="task_assistance",
        snapshots=(_memory_snapshot("mem-own", owner_id, "自己的记忆"),),
    )

    # 正对照：自己的 manifest 必须查得到——先证明端点确实存在，
    # 后面的 404 才是「跨 owner 被拒绝」而不是「路由没注册」。
    own = authed_client.get(DETAIL_PATH.format(manifest_id=own_manifest_id))
    assert own.status_code == 200, own.text

    detail = authed_client.get(DETAIL_PATH.format(manifest_id=other_manifest_id))
    assert detail.status_code == 404, detail.text
    _assert_project_error(detail)

    listing = authed_client.get(LIST_PATH)
    assert listing.status_code == 200, listing.text
    assert other_manifest_id not in [item["id"] for item in listing.json()["items"]]


def test_get_context_manifest_returns_404_for_a_missing_record(app: FastAPI, authed_client: TestClient) -> None:
    """不存在的记录返回项目约定的资源错误。"""
    database = _app_database(app)
    owner_id = _owner_id(authed_client)
    job_id = _insert_job(database, owner_id)
    manifest_id = _seed_manifest(
        database,
        owner_id,
        job_id=job_id,
        step="task_assistance",
        snapshots=(_memory_snapshot("mem-1", owner_id, "甲"),),
    )

    # 正对照：端点存在时，已有记录必须查得到。
    existing = authed_client.get(DETAIL_PATH.format(manifest_id=manifest_id))
    assert existing.status_code == 200, existing.text

    response = authed_client.get(DETAIL_PATH.format(manifest_id=str(uuid.uuid4())))

    assert response.status_code == 404, response.text
    _assert_project_error(response)


def test_list_context_manifests_filters_by_job_id_and_step(app: FastAPI, authed_client: TestClient) -> None:
    """查询维度：owner 由服务端绑定，job_id 与 step 是可组合的过滤条件。"""
    database = _app_database(app)
    owner_id = _owner_id(authed_client)
    job_id = _insert_job(database, owner_id)
    other_job_id = _insert_job(database, owner_id)
    wanted = _seed_manifest(
        database,
        owner_id,
        job_id=job_id,
        step="task_assistance",
        snapshots=(_memory_snapshot("mem-1", owner_id, "甲"),),
    )
    _seed_manifest(
        database,
        owner_id,
        job_id=other_job_id,
        step="goal_clarification",
        snapshots=(_memory_snapshot("mem-2", owner_id, "乙"),),
    )

    by_job = authed_client.get(LIST_PATH, params={"job_id": job_id})
    assert by_job.status_code == 200, by_job.text
    assert [item["id"] for item in by_job.json()["items"]] == [wanted]

    by_step = authed_client.get(LIST_PATH, params={"step": "goal_clarification"})
    assert by_step.status_code == 200, by_step.text
    assert wanted not in [item["id"] for item in by_step.json()["items"]]

    combined = authed_client.get(LIST_PATH, params={"job_id": job_id, "step": "goal_clarification"})
    assert combined.status_code == 200, combined.text
    assert combined.json()["items"] == []


def test_list_context_manifests_is_stable_across_repeated_calls(app: FastAPI, authed_client: TestClient) -> None:
    """返回顺序按创建时间稳定，重复查询结果逐字一致。"""
    database = _app_database(app)
    owner_id = _owner_id(authed_client)
    job_id = _insert_job(database, owner_id)
    later = _seed_manifest(
        database,
        owner_id,
        job_id=job_id,
        step="task_assistance",
        snapshots=(_memory_snapshot("mem-later", owner_id, "后"),),
    )
    earlier = _seed_manifest(
        database,
        owner_id,
        job_id=job_id,
        step="task_assistance",
        snapshots=(_memory_snapshot("mem-earlier", owner_id, "前"),),
    )
    # 故意让「先写的」created_at 更晚：顺序必须看创建时间，不能看插入顺序。
    _set_created_at(database, later, datetime(2026, 10, 28, 12, 0, 1, tzinfo=UTC))
    _set_created_at(database, earlier, datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC))

    first = authed_client.get(LIST_PATH)
    second = authed_client.get(LIST_PATH)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert [item["id"] for item in first.json()["items"]] == [earlier, later]
    assert first.json() == second.json()


def test_context_manifest_reports_the_strategy_revision_used_at_assembly_time(
    app: FastAPI, authed_client: TestClient
) -> None:
    """清单里的策略版本就是装配当时用的那个版本。

    带检索证据的步骤用的是 L3+L4 组合版本（agent/memory_context.py::manifest_strategy_revision），
    这里用生产函数取期望值，避免把版本串写死在测试里。
    """
    database = _app_database(app)
    owner_id = _owner_id(authed_client)
    job_id = _insert_job(database, owner_id)
    expected = manifest_strategy_revision(TASK_ASSISTANCE)
    assert expected == f"{L3_STRATEGY_REVISION}+{L4_STRATEGY_REVISION}"
    _seed_manifest(
        database,
        owner_id,
        job_id=job_id,
        step=TASK_ASSISTANCE,
        snapshots=(_memory_snapshot("mem-1", owner_id, "甲"),),
        strategy_revision=expected,
    )

    response = authed_client.get(LIST_PATH)

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["strategy_revision"] == expected


def test_context_manifest_endpoints_require_authentication(client: TestClient) -> None:
    """未登录访问返回 401，不泄露清单是否存在。"""
    listing = client.get(LIST_PATH)
    assert listing.status_code == 401, listing.text

    detail = client.get(DETAIL_PATH.format(manifest_id=str(uuid.uuid4())))
    assert detail.status_code == 401, detail.text
