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

"""Offline CSV records captured with document- and primary-key-stable identities."""

from __future__ import annotations

import csv
import io
import json
from typing import Self
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import SourceDefinition, SourceProjection
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


def _validate_document_id(document_id: str) -> None:
    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty and have no surrounding whitespace")  # noqa: TRY003


def _primary_key_index(columns: tuple[str, ...], primary_key: str) -> int:
    if not columns or any(not column.strip() for column in columns):
        raise ValueError("CSV headers must be non-empty and not blank")  # noqa: TRY003
    if len(set(columns)) != len(columns):
        raise ValueError("CSV headers must be unique")  # noqa: TRY003
    if not primary_key or primary_key not in columns:
        raise ValueError("primary_key must exactly match a CSV header")  # noqa: TRY003
    return columns.index(primary_key)


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Encode an exact row identity, rejecting invalid or overlong components.

    >>> csv_row_source_id("airports:control", " key/01 ")
    'csv:airports%3Acontrol:%20key%2F01%20'
    """
    _validate_document_id(document_id)
    if not primary_key_value.strip():
        raise ValueError("CSV primary key values must not be empty or blank")  # noqa: TRY003
    identity = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError("CSV row identity exceeds the Source ID length limit")  # noqa: TRY003
    return identity


def _validate_row(
    document_id: str,
    primary_key: str,
    primary_key_value: str,
    columns: tuple[str, ...],
    values: tuple[str, ...],
) -> str:
    index = _primary_key_index(columns, primary_key)
    if len(values) != len(columns):
        raise ValueError("CSV row width must match the header width")  # noqa: TRY003
    if values[index] != primary_key_value:
        raise ValueError("primary_key_value must match the row's primary key field")  # noqa: TRY003
    return csv_row_source_id(document_id, primary_key_value)


class CSVDocumentInput(BaseModel):
    """A complete offline CSV document and the exact name of its primary key column."""

    document_id: str
    primary_key: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        _validate_document_id(value)
        return value

    @field_validator("primary_key")
    @classmethod
    def validate_primary_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("primary_key must not be empty or blank")  # noqa: TRY003
        return value


class CSVRowInput(BaseModel):
    """One validated record, preserving the original header order and string values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self) -> Self:
        _validate_row(self.document_id, self.primary_key, self.primary_key_value, self.columns, self.values)
        return self


class CSVRowSource(Source):
    """A captured record whose complete fields can be read without its original CSV."""

    model_config = ConfigDict(revalidate_instances="always")

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row_source(self) -> Self:
        identity = _validate_row(self.document_id, self.primary_key, self.primary_key_value, self.columns, self.values)
        if self.source_id != identity or self.name != identity:
            raise ValueError("CSV Source name and source_id must match the row identity")  # noqa: TRY003
        if self.materialization is not SourceMaterialization.CAPTURED:
            raise ValueError("CSV row Sources must retain their captured fields")  # noqa: TRY003
        return self


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Validate the entire document before returning any records.

    Empty physical records after the header are ignored. Empty fields, whitespace,
    embedded newlines and quoted values otherwise keep their exact string values.
    Encoding, CSV syntax and record validation failures raise ``ValueError``.
    """
    _validate_document_id(value.document_id)
    try:
        content = value.content.decode("utf-8-sig", errors="strict")
        reader = csv.reader(
            io.StringIO(content, newline=""), delimiter=",", quotechar='"', doublequote=True, strict=True
        )
        columns = tuple(next(reader, ()))
        key_index = _primary_key_index(columns, value.primary_key)
        rows: list[CSVRowInput] = []
        seen: set[str] = set()
        for fields in reader:
            if not fields:
                continue
            if len(fields) != len(columns):
                raise ValueError("CSV row width must match the header width")  # noqa: TRY003
            key = fields[key_index]
            if key in seen:
                raise ValueError("CSV primary key values must be unique within a document")  # noqa: TRY003
            row = CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=key,
                columns=columns,
                values=tuple(fields),
            )
            seen.add(key)
            rows.append(row)
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError("Invalid UTF-8 CSV document") from error  # noqa: TRY003
    return tuple(rows)


class _CSVRowDefinition:
    input_class: type[CSVRowInput] = CSVRowInput
    name = "csv-row"
    version = "1"
    source_class: type[CSVRowSource] = CSVRowSource

    def __init__(self) -> None:
        self.projections: tuple[SourceProjection[CSVRowSource], ...] = (_CSVRowTextEvidenceProjection(),)

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        source = CSVRowSource.model_validate(source)
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class _CSVRowTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[CSVRowSource] = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        source = CSVRowSource.model_validate(source)
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type="csv-row",
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = _CSVRowDefinition()

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
