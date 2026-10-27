"""真实 PowerContext 联调脚本的本地可验证部分测试。

**这些测试只检查脚本本身**：文件是否在、能否按 UTF-8 读取、是不是纯标准库、
URL 与 Scope 是否来自环境变量或命令行、有没有把真实 Token 写死、两个会话标识
是否在脚本里、以及 `recorded` / `memory_status` / `ready` 这些关键断言是否确实存在。

它们**不会发起任何网络请求**，也**不能代替真实联调**：本文件既没有启动 Arena，
也没有启动 PowerContext，更没有写入任何记忆。真实两会话「翻旧账」的运行结果
记录在 ``dify/ai-debate-show/evidence/powercontext-e2e.md``，需要真实环境才能复现。
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "verify-powercontext-e2e.py"
EVIDENCE_PATH = PROJECT_DIR / "evidence" / "powercontext-e2e.md"

# 明显是真实凭据的前缀，脚本里一个都不该有。
CREDENTIAL_MARKERS = ("sk-", "ghp_", "AKIA", "eyJ")

# 脚本不允许依赖的第三方库与内部实现。
FORBIDDEN_IMPORTS = (
    "import requests",
    "from requests",
    "import httpx",
    "from httpx",
    "import pytest",
    "import fastapi",
    "import pydantic",
    "from arena_service",
    "import arena_service",
    "from powercontext",
    "import powercontext",
)


def _read(path: Path) -> str:
    """按 UTF-8 读取；带 BOM 或无法解码直接失败。"""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise AssertionError(f"{path.name} 不应带 UTF-8 BOM")
    return raw.decode("utf-8")


def _load_script():
    """按文件路径加载脚本模块；脚本名带连字符，不能直接 import。"""
    spec = importlib.util.spec_from_file_location("verify_powercontext_e2e", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScriptPresenceTest(unittest.TestCase):
    """脚本与证据文件是否在、可读。"""

    def test_script_exists(self) -> None:
        self.assertTrue(SCRIPT_PATH.is_file(), f"缺少脚本：{SCRIPT_PATH}")

    def test_script_is_utf8_without_bom(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn("真实 PowerContext", source)

    def test_evidence_file_is_utf8(self) -> None:
        self.assertTrue(EVIDENCE_PATH.is_file(), f"缺少证据文件：{EVIDENCE_PATH}")
        self.assertIn("PowerContext 已实际用于保存会话一记忆", _read(EVIDENCE_PATH))


class ScriptDependencyTest(unittest.TestCase):
    """脚本是否只用标准库、且不依赖内部实现。"""

    def test_script_uses_only_standard_library(self) -> None:
        source = _read(SCRIPT_PATH)
        for marker in FORBIDDEN_IMPORTS:
            self.assertNotIn(marker, source, f"脚本不应依赖 {marker!r}")

    def test_script_uses_urllib_only(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn("import urllib.request", source)
        self.assertIn("import json", source)
        self.assertIn("import argparse", source)


class ScriptConfigurationTest(unittest.TestCase):
    """URL 与 Scope 是否来自环境变量或命令行，而不是写死。"""

    def test_script_reads_urls_from_environment(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn("ARENA_BASE_URL", source)
        self.assertIn("POWERCONTEXT_BASE_URL", source)
        self.assertIn("POWERCONTEXT_SCOPE_ID", source)

    def test_script_accepts_scope_and_urls_from_command_line(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn('"--scope-id"', source)
        self.assertIn('"--arena-base-url"', source)
        self.assertIn('"--powercontext-base-url"', source)

    def test_script_has_no_hardcoded_scope(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertNotIn("scp_", source, "脚本不应写死任何 scope_id")


class ScriptCredentialHygieneTest(unittest.TestCase):
    """脚本不得包含真实凭据。"""

    def test_script_contains_no_real_credential(self) -> None:
        source = _read(SCRIPT_PATH)
        for marker in CREDENTIAL_MARKERS:
            self.assertNotIn(marker, source, f"脚本不应包含疑似真实凭据 {marker!r}")

    def test_token_is_only_read_from_environment(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn('os.environ.get("POWERCONTEXT_BEARER_TOKEN")', source)

    def test_redaction_replaces_registered_secret(self) -> None:
        module = _load_script()
        module.register_secret("s3cr3t-token-value")
        try:
            self.assertNotIn(
                "s3cr3t-token-value",
                module.redact("响应里混进了 s3cr3t-token-value 这个令牌"),
            )
            self.assertIn("***", module.redact("响应里混进了 s3cr3t-token-value 这个令牌"))
        finally:
            module._SECRETS.clear()


class ScriptScenarioTest(unittest.TestCase):
    """两个会话与关键断言是否都在脚本里。"""

    def test_script_contains_both_session_ids(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn("pc-e2e-session-one", source)
        self.assertIn("pc-e2e-session-two", source)

    def test_script_asserts_recorded_status(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn("recorded", source)
        self.assertIn("'recorded'", source)

    def test_script_asserts_memory_status_and_ready(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn("memory_status", source)
        self.assertIn("'ready'", source)

    def test_script_checks_recall_keywords(self) -> None:
        source = _read(SCRIPT_PATH)
        for keyword in ("反对", "珍珠", "没有手"):
            self.assertIn(keyword, source)

    def test_script_uses_expected_fixed_parameters(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn("pearl-voting-rights", source)
        self.assertIn("logic-monster", source)
        self.assertIn("阿强", source)
        self.assertIn("double_down", source)


class ScriptOfflineBehaviourTest(unittest.TestCase):
    """脚本在缺参数时应当立刻退出，而不是去发请求。"""

    def test_missing_configuration_exits_without_network(self) -> None:
        module = _load_script()
        clean = {
            "ARENA_BASE_URL": "",
            "POWERCONTEXT_BASE_URL": "",
            "POWERCONTEXT_SCOPE_ID": "",
        }
        with mock.patch.dict(os.environ, clean, clear=False):
            for key in clean:
                os.environ.pop(key, None)
            with mock.patch("sys.stderr"):
                exit_code = module.main([])
        self.assertEqual(exit_code, 2, "缺少 URL 或 Scope 时应返回退出码 2")

    def test_main_is_guarded_by_main_block(self) -> None:
        source = _read(SCRIPT_PATH)
        self.assertIn('if __name__ == "__main__":', source)


if __name__ == "__main__":
    unittest.main()
