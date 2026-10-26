# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryCitation, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    SourceDefinitionRegistry,
    SourceObservation,
    TextEvidence,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    CSVRowSource,
    csv_row_source_id,
    parse_csv_document,
)


class RowEvidencePipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
        entries = []
        for source in request.sources:
            evidence = TextEvidence.model_validate(registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY))
            entries.append(MemoryEntryInput(kind="csv-row", text=evidence.content, sources=(source,)))
        return tuple(entries)


_READ_IN_FRESH_PROCESS = """
import asyncio
import json
import sys

from powercontext.builtin.artifacts.memory import MemoryCitation
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, GetMemoryEntryRequest, open_builtin_contexts, open_builtin_runtime
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY

state = json.load(sys.stdin)
config = BuiltinConfig(database=SQLiteConfig(url=state["database_url"]))

async def read():
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(state["scope_id"])
        for source_id, value in state["citations"].items():
            citation = MemoryCitation.model_validate(value)
            entry = await memory.get(GetMemoryEntryRequest(citation=citation))
            assert entry.entry.text == state["evidence"][source_id]["content"]
            assert entry.entry.sources[0].source_id == source_id
    async with open_builtin_contexts(config) as contexts:
        entries = await (await contexts.get(state["scope_id"])).sources.journal.entries()
        assert len(entries) == len(state["evidence"])
        for entry in entries:
            evidence = entry.source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
            assert evidence == state["evidence"][evidence["source_id"]]
            assert list(evidence["metadata"]["row"]) == evidence["metadata"]["columns"]

asyncio.run(read())
"""


def test_unicode_rows_and_each_exact_citation_survive_reopening_sqlite(tmp_path: Path) -> None:
    rows = parse_csv_document(
        CSVDocumentInput(
            document_id="机场:原表/一",
            primary_key=" id ",
            content=(
                "z, id ,名称,empty,flag\r\n"
                'QuasarAirport, 001 ,"上海,东站",,false\r\n'
                'PulsarAirport,001,"第一行\r\n第二行 ""备注""",,true\r\n'
            ).encode(),
        )
    ) + parse_csv_document(
        CSVDocumentInput(
            document_id="机场:原表/二",
            primary_key=" id ",
            content="z, id ,名称,empty,flag\nNebulaAirport,001,另一文档,,0\n".encode(),
        )
    )
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'rows.db').as_posix()}"
    config = BuiltinConfig(database=SQLiteConfig(url=database_url))
    persisted: dict[str, object] = {}

    async def scenario() -> None:
        expected: dict[str, TextEvidence] = {}
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="CSV 字段保真", summary="Offline row evidence", idempotency_key="csv-regression")
            )
            await runtime.ingestion.register(manifest_for_definition(CSV_ROW_SOURCE_DEFINITION))
            for row in rows:
                source = await registry.resolve(row)
                evidence = TextEvidence.model_validate(registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY))
                expected[evidence.source_id] = evidence
                observation = project_source_for_transport(registry, source)
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )
                # Identical observations must remain idempotent through the native ingestion path.
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )

        citations: dict[str, MemoryCitation] = {}
        async with open_builtin_runtime(config, candidate_pipeline=RowEvidencePipeline()) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            processed = 0
            for _ in range(len(rows) + 1):
                result = await memory.flush()
                if not result.processed:
                    break
                processed += result.source_count
            assert processed == len(rows)
            for row in rows:
                result = await memory.search(SearchMemoryRequest(query=row.values[0], mode="fts", limit=10))
                assert len(result.hits) == 1
                hit = result.hits[0]
                citation = MemoryCitation(
                    memory_ref=hit.memory_ref,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                )
                entry = await memory.get(GetMemoryEntryRequest(citation=citation))
                assert len(entry.entry.sources) == 1
                source_id = entry.entry.sources[0].source_id
                assert entry.entry.text == expected[source_id].content
                citations[source_id] = citation
            assert set(citations) == set(expected)

        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            for source_id, citation in citations.items():
                entry = await memory.get(GetMemoryEntryRequest(citation=citation))
                assert entry.entry.text == expected[source_id].content

        async with open_builtin_contexts(config) as contexts:
            journal = await (await contexts.get(scope.scope_id)).sources.journal.entries()
            assert len(journal) == len(rows)
            rows_by_id = {csv_row_source_id(row.document_id, row.primary_key_value): row for row in rows}
            for entry in journal:
                observation = entry.source
                assert isinstance(observation, SourceObservation)
                evidence = TextEvidence.model_validate(registry.project(observation, TEXT_EVIDENCE_PROJECTION_KEY))
                assert evidence == expected[evidence.source_id]
                columns = evidence.metadata["columns"]
                row_mapping = evidence.metadata["row"]
                assert isinstance(columns, list)
                assert isinstance(row_mapping, dict)
                assert list(json.loads(evidence.content)) == columns
                assert list(row_mapping) == columns
                source = CSVRowSource.model_validate_json(json.dumps(observation.payload))
                assert await registry.read(source) == rows_by_id[evidence.source_id]
        persisted.update(
            database_url=database_url,
            scope_id=scope.scope_id,
            citations={key: citation.model_dump(mode="json") for key, citation in citations.items()},
            evidence={key: evidence.model_dump(mode="json") for key, evidence in expected.items()},
        )

    asyncio.run(scenario())
    result = subprocess.run(
        [sys.executable, "-c", _READ_IN_FRESH_PROCESS],
        input=json.dumps(persisted),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
