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
import csv
import io
import json

import pytest

from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    SourceDefinitionRegistry,
    SourceMaterialization,
    TextEvidence,
)
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    CSVRowInput,
    CSVRowSource,
    csv_row_source_id,
    parse_csv_document,
)


def test_definition_preserves_order_strings_and_unicode_through_json_roundtrip() -> None:
    content = '\ufeffz, id ,名称,empty,flag\r\n"原文\r\n第二行", 001 ,"机场,东站",,false\r\n'.encode()
    (row,) = parse_csv_document(CSVDocumentInput(document_id="机场:表/一", primary_key=" id ", content=content))
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    assert CSV_ROW_SOURCE_DEFINITION.name == "csv-row"
    assert CSV_ROW_SOURCE_DEFINITION.version == "1"
    assert CSV_ROW_SOURCE_DEFINITION.input_class is CSVRowInput
    assert CSV_ROW_SOURCE_DEFINITION.source_class is CSVRowSource
    assert row.values == ("原文\r\n第二行", " 001 ", "机场,东站", "", "false")

    source = asyncio.run(registry.resolve(row))
    restored = CSVRowSource.model_validate_json(source.model_dump_json())
    assert restored.materialization is SourceMaterialization.CAPTURED
    assert restored.name == restored.source_id == csv_row_source_id("机场:表/一", " 001 ")
    assert asyncio.run(registry.read(restored)) == row
    evidence = TextEvidence.model_validate(registry.project(restored, TEXT_EVIDENCE_PROJECTION_KEY))
    expected = dict(zip(row.columns, row.values, strict=True))
    assert evidence.content == json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
    assert list(json.loads(evidence.content)) == list(row.columns)
    assert evidence.metadata == {
        "document_id": row.document_id,
        "primary_key": row.primary_key,
        "primary_key_value": row.primary_key_value,
        "columns": list(row.columns),
        "row": expected,
    }


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", "\r"])
def test_only_empty_physical_records_are_ignored(line_ending: str) -> None:
    content = line_ending.join(["id,note", "", '01,""', "", "02, ", ""]).encode()
    rows = parse_csv_document(CSVDocumentInput(document_id="blank-records", primary_key="id", content=content))
    assert [row.values for row in rows] == [("01", ""), ("02", " ")]


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xef\xbb\xbf",
        b"\nid,name\n1,one\n",
        b'""\n',
        b"id,\t\n1,value\n",
        b"id,name,name\n1,a,b\n",
        b"id,name\n1,valid\n1,duplicate\n",
        b"id,name\n1,valid\n,empty-key\n",
        b"id,name\n1,valid\n \t,blank-key\n",
        b"id,name\n1,valid\n2\n",
        b"id,name\n1,valid\n2,too,many\n",
        b"id,name\n1,valid\n,,\n",
        b'id,name\n1,valid\n""\n',
        b"id,name\n1,valid\n   \n",
        b'id,name\n1,valid\n2,"unfinished\n',
        b'id,name\n1,valid\n2,"quoted"suffix\n',
        b"id,name\n1,valid\n2,\xff\n",
    ],
)
def test_invalid_document_raises_instead_of_returning_valid_prefix(content: bytes) -> None:
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id="atomic", primary_key="id", content=content))


def test_distinct_header_and_key_whitespace_is_not_normalized() -> None:
    rows = parse_csv_document(
        CSVDocumentInput(document_id="spaces", primary_key=" id ", content=b"id, id \na, key \nb,key\nc,key \n")
    )
    assert [row.primary_key_value for row in rows] == [" key ", "key", "key "]
    assert len({csv_row_source_id(row.document_id, row.primary_key_value) for row in rows}) == 3
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id="spaces", primary_key="id", content=b" id ,name\na,b\n"))


@pytest.mark.parametrize("document_id", ["", " ", " doc", "doc ", "\tdoc", "doc\n"])
def test_invalid_document_identity_is_rejected(document_id: str) -> None:
    with pytest.raises(ValueError):
        csv_row_source_id(document_id, "key")
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id=document_id, primary_key="id", content=b"id\nkey\n"))


@pytest.mark.parametrize("key", ["", " ", "\t\r\n"])
def test_blank_primary_key_values_are_rejected(key: str) -> None:
    with pytest.raises(ValueError):
        csv_row_source_id("doc", key)


def test_identity_has_no_delimiter_or_percent_encoding_collisions() -> None:
    pairs = [("a:b", "c"), ("a", "b:c"), ("a%3Ab", "c"), ("a/b", "c"), ("a", "b/c")]
    assert len({csv_row_source_id(document, key) for document, key in pairs}) == len(pairs)
    assert csv_row_source_id("文档", " a/%: ") == "csv:%E6%96%87%E6%A1%A3:%20a%2F%25%3A%20"


def test_identity_length_is_checked_after_encoding_including_prefix_and_separators() -> None:
    assert len(csv_row_source_id("doc", "x" * 248)) == 256
    assert len(csv_row_source_id("d", "中" * 27 + "x" * 7)) == 256
    for document_id, key in [("doc", "x" * 249), ("d", "中" * 28), ("d" * 252, "x")]:
        with pytest.raises(ValueError):
            csv_row_source_id(document_id, key)
        output = io.StringIO(newline="")
        csv.writer(output).writerows([("id",), (key,)])
        with pytest.raises(ValueError):
            parse_csv_document(
                CSVDocumentInput(document_id=document_id, primary_key="id", content=output.getvalue().encode())
            )


@pytest.mark.parametrize("primary_key", ["", " ", "missing", " id "])
def test_header_only_documents_still_validate_primary_key(primary_key: str) -> None:
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id="empty", primary_key=primary_key, content=b"id,name\n"))


def test_header_only_document_returns_empty_tuple() -> None:
    assert parse_csv_document(CSVDocumentInput(document_id="empty", primary_key="id", content=b"id,name")) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"columns": ()},
        {"columns": ("id", "id")},
        {"columns": ("id", " ")},
        {"values": ("key",)},
        {"values": ("key", "value", "extra")},
        {"primary_key": "missing"},
        {"primary_key_value": "different"},
        {"primary_key_value": " ", "values": (" ", "value")},
        {"document_id": " doc "},
        {"document_id": "x" * 256},
    ],
)
def test_direct_row_inputs_obey_the_same_record_invariants(changes: dict[str, object]) -> None:
    data = {
        "document_id": "doc",
        "primary_key": "id",
        "primary_key_value": "key",
        "columns": ("id", "name"),
        "values": ("key", "value"),
    }
    with pytest.raises(ValueError):
        CSVRowInput.model_validate(data | changes)


@pytest.mark.parametrize("changes", [{"name": "other"}, {"source_id": "other"}, {"materialization": "referenced"}])
def test_source_cannot_claim_a_different_identity_or_read_authority(changes: dict[str, str]) -> None:
    (row,) = parse_csv_document(CSVDocumentInput(document_id="doc", primary_key="id", content=b"id\nkey\n"))
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    source = asyncio.run(registry.resolve(row))
    with pytest.raises(ValueError):
        CSVRowSource.model_validate(source.model_dump() | changes)


def test_resolve_rechecks_mutated_inputs_before_creating_a_source() -> None:
    row = CSVRowInput(document_id="doc", primary_key="id", primary_key_value="key", columns=("id",), values=("key",))
    row.values = ("other",)
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    with pytest.raises(ValueError):
        asyncio.run(registry.resolve(row))
