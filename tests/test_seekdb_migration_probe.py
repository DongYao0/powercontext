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

"""A skipped test or retained engine must not certify native recovery."""

import json
from pathlib import Path

import pytest

from scripts.probe_seekdb_migration_lock import restart_evidence, successful_report


@pytest.mark.parametrize("outcome", ["", "<skipped/>", "<failure/>", "<error/>"])
def test_native_acceptance_requires_one_passing_case(tmp_path: Path, outcome: str) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(f"<testsuite><testcase>{outcome}</testcase></testsuite>")
    assert successful_report(report, 0) is (outcome == "")
    assert not successful_report(report, 1)
    report.write_text("<testsuite/>")
    assert not successful_report(report, 0)


@pytest.mark.parametrize("pids, accepted", [([], False), ([101], False), ([101, 101], False), ([101, 102], True)])
def test_restart_acceptance_rejects_an_engine_kept_alive(tmp_path: Path, pids: list[int], accepted: bool) -> None:
    events = [{"event": "opened", "path": "/synthetic/seekdb", "native_pid": pid} for pid in pids]
    (tmp_path / "lifecycle.jsonl").write_text("\n".join(json.dumps(event) for event in events))
    assert restart_evidence(tmp_path)["passed"] is accepted
