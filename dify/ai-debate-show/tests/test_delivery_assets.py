"""《再说一遍？》提交包交付资产的完整性测试。

**这些测试只检查交付物本身**：文件是否齐全、能否按 UTF-8 读取、README 是否覆盖评审
需要找到的内容、启动脚本是否包含规定的命令与安全约束、验证剧本是否包含规定的场景
与断言、导入说明是否写了 Scope 准备。

它们不能替代真实运行；真实 Dify 与 PowerContext 联调的结果记录在
``dify/ai-debate-show/evidence/dify-e2e.md``。本文件只证明提交资产本身完整、可读且自洽。
"""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
README_PATH = PROJECT_DIR / "README.md"
ENV_EXAMPLE_PATH = PROJECT_DIR / ".env.example"
BAT_PATH = PROJECT_DIR / "scripts" / "start-arena.bat"
SH_PATH = PROJECT_DIR / "scripts" / "start-arena.sh"
GUIDE_PATH = PROJECT_DIR / "examples" / "verification-guide.md"
IMPORT_PATH = PROJECT_DIR / "dify" / "DIFY_IMPORT.md"
E2E_EVIDENCE_PATH = PROJECT_DIR / "evidence" / "dify-e2e.md"

# 明显是真实凭据的前缀，交付物里一个都不该有。
CREDENTIAL_MARKERS = ("sk-", "Bearer ", "ghp_", "AKIA", "eyJ")

# 启动脚本绝对不允许出现的动作。
FORBIDDEN_IN_SCRIPTS = ("taskkill", "kill -9", "Bearer ")


def _read(path: Path) -> str:
    """按 UTF-8 读取交付资产；带 BOM 或无法解码直接失败。"""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise AssertionError(f"{path.name} 不应带 UTF-8 BOM")
    return raw.decode("utf-8")


def _has_bare_lf(raw: bytes) -> bool:
    """是否存在没有配对 CR 的换行符。"""
    return b"\n" in raw.replace(b"\r\n", b"")


def _has_crlf(raw: bytes) -> bool:
    """是否存在 CRLF 换行符。"""
    return b"\r\n" in raw


class DeliveryAssetPresenceTest(unittest.TestCase):
    """交付物是否齐全、可读。"""

    def test_all_delivery_files_exist(self) -> None:
        for path in (
            README_PATH,
            ENV_EXAMPLE_PATH,
            BAT_PATH,
            SH_PATH,
            GUIDE_PATH,
            IMPORT_PATH,
            E2E_EVIDENCE_PATH,
        ):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), f"缺少交付文件：{path}")
                self.assertGreater(path.stat().st_size, 0, f"{path.name} 是空文件")

    def test_all_delivery_files_are_utf8_without_bom(self) -> None:
        for path in (
            README_PATH,
            ENV_EXAMPLE_PATH,
            BAT_PATH,
            SH_PATH,
            GUIDE_PATH,
            IMPORT_PATH,
            E2E_EVIDENCE_PATH,
        ):
            with self.subTest(path=path.name):
                text = _read(path)
                self.assertTrue(text.strip(), f"{path.name} 只有空白")

    def test_line_endings_are_consistent(self) -> None:
        """Windows 批处理用 CRLF，POSIX 脚本与文档用 LF。"""
        self.assertFalse(
            _has_bare_lf(BAT_PATH.read_bytes()),
            "start-arena.bat 应使用 CRLF 换行",
        )
        for path in (SH_PATH, README_PATH, ENV_EXAMPLE_PATH, GUIDE_PATH):
            with self.subTest(path=path.name):
                self.assertFalse(
                    _has_crlf(path.read_bytes()),
                    f"{path.name} 应使用 LF 换行",
                )


class ReadmeContentTest(unittest.TestCase):
    """README 是评审第一入口，必须覆盖到关键内容。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.readme = _read(README_PATH)

    def test_contains_required_topics(self) -> None:
        for keyword in (
            "Dify",
            "Arena",
            "PowerContext",
            "快速启动",
            "验证",
            "已知限制",
        ):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, self.readme)

    def test_contains_architecture_relationship(self) -> None:
        for line in (
            "玩家",
            "Dify Chatflow",
            "↓ HTTP Request",
            "Arena API",
            "├─ 内容目录、反击卡、三回合状态机",
            "└─ PowerContext",
            "├─ 开局历史上下文召回",
            "└─ 第三回合结算记忆写入",
        ):
            with self.subTest(line=line):
                self.assertIn(line, self.readme)

    def test_states_the_three_layer_division_of_labour(self) -> None:
        self.assertIn("seekdb", self.readme)
        self.assertIn("确定性规则层", self.readme)
        self.assertIn("跨会话", self.readme)

    def test_links_to_import_guide_and_verification_guide(self) -> None:
        self.assertIn("dify/DIFY_IMPORT.md", self.readme)
        self.assertIn("examples/verification-guide.md", self.readme)

    def test_states_real_end_to_end_result_honestly(self) -> None:
        """README 必须给出已验证全链路的证据入口。"""
        self.assertIn("静态测试", self.readme)
        self.assertIn("Dify 1.17.1", self.readme)
        self.assertIn("两会话翻旧账全链路验证", self.readme)
        self.assertIn("evidence/dify-e2e.md", self.readme)

    def test_has_no_trailing_whitespace(self) -> None:
        for number, line in enumerate(self.readme.split("\n"), start=1):
            self.assertEqual(line, line.rstrip(), f"README.md 第 {number} 行有行尾空白")


class EnvExampleTest(unittest.TestCase):
    """.env.example 只放占位配置。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(ENV_EXAMPLE_PATH)

    def test_declares_the_five_environment_variables(self) -> None:
        for name in (
            "ARENA_HOST",
            "ARENA_PORT",
            "POWERCONTEXT_BASE_URL",
            "POWERCONTEXT_BEARER_TOKEN",
            "POWERCONTEXT_TIMEOUT_SECONDS",
        ):
            with self.subTest(name=name):
                self.assertIn(f"{name}=", self.text)

    def test_contains_no_credential_markers(self) -> None:
        for marker in CREDENTIAL_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.text)

    def test_contains_no_user_machine_paths(self) -> None:
        for marker in ("C:\\Users", "/Users/", "/home/"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.text)


class StartupScriptTest(unittest.TestCase):
    """启动脚本：定位项目、检查依赖与端口、前台启动、不杀进程。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bat = _read(BAT_PATH)
        cls.sh = _read(SH_PATH)

    def test_windows_script_starts_the_server(self) -> None:
        self.assertIn("python -m arena_service.server", self.bat)

    def test_unix_script_starts_the_server(self) -> None:
        self.assertIn("python3 -m arena_service.server", self.sh)

    def test_scripts_never_kill_processes(self) -> None:
        for name, text in (("start-arena.bat", self.bat), ("start-arena.sh", self.sh)):
            for forbidden in FORBIDDEN_IN_SCRIPTS:
                with self.subTest(script=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_scripts_set_pythonpath_to_project_dir(self) -> None:
        self.assertIn("PYTHONPATH", self.bat)
        self.assertIn("PYTHONPATH", self.sh)

    def test_scripts_check_port_and_python(self) -> None:
        self.assertIn("8088", self.bat)
        self.assertIn("8088", self.sh)
        self.assertIn("python", self.bat)
        self.assertIn("python3", self.sh)

    def test_scripts_do_not_install_dependencies(self) -> None:
        for name, text in (("start-arena.bat", self.bat), ("start-arena.sh", self.sh)):
            for forbidden in ("pip install", "pip3 install", "uv pip", "poetry install"):
                with self.subTest(script=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_scripts_never_print_the_token_value(self) -> None:
        """脚本只能说"是否配置了记忆能力"，不能回显令牌。"""
        for name, text in (("start-arena.bat", self.bat), ("start-arena.sh", self.sh)):
            with self.subTest(script=name):
                self.assertNotIn("%POWERCONTEXT_BEARER_TOKEN%", text)
                self.assertNotIn("${POWERCONTEXT_BEARER_TOKEN}", text)
                self.assertNotIn("$POWERCONTEXT_BEARER_TOKEN", text)


class VerificationGuideTest(unittest.TestCase):
    """验收剧本必须覆盖两套场景与全部断言。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.guide = _read(GUIDE_PATH)

    def test_contains_both_scenarios(self) -> None:
        for keyword in ("场景 A", "场景 B"):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, self.guide)

    def test_contains_two_session_scenario(self) -> None:
        self.assertIn("两会话", self.guide)
        self.assertIn("会话一", self.guide)
        self.assertIn("会话二", self.guide)

    def test_contains_expected_markers(self) -> None:
        self.assertIn('memory_status="ready"', self.guide)
        self.assertIn("recorded", self.guide)

    def test_contains_troubleshooting_order(self) -> None:
        self.assertIn("排障顺序", self.guide)
        for step in (
            "先确认会话一记忆写入是否 returned",
            "确认两会话",
            "确认 Arena 没有进入 degraded",
            "确认 PowerContext 服务地址与认证",
            "不得通过伪造",
        ):
            with self.subTest(step=step):
                self.assertIn(step, self.guide)

    def test_contains_degraded_scenario_expectations(self) -> None:
        for keyword in (
            "memory_status",
            "degraded",
            "memory_unavailable",
            "game_finished=true",
            "127.0.0.1:8088",
        ):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, self.guide)


class ImportGuideScopeTest(unittest.TestCase):
    """导入说明必须写清 Scope 准备。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(IMPORT_PATH)

    def test_contains_scope_preparation_section(self) -> None:
        self.assertIn("Scope 准备", self.text)
        self.assertIn("POST /v1/scopes", self.text)
        self.assertIn("idempotency_key", self.text)

    def test_contains_scope_creation_constraints(self) -> None:
        for keyword in ("201", "权限", "预分配", "不得根据昵称"):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, self.text)

    def test_contains_both_example_styles(self) -> None:
        self.assertIn("curl", self.text)
        self.assertIn("Invoke-RestMethod", self.text)


class HonestScopeTest(unittest.TestCase):
    """文档资产测试自身的边界声明。"""

    def test_module_docstring_states_the_limit(self) -> None:
        doc = __doc__ or ""
        self.assertIn("不能替代", doc)
        self.assertIn("Dify", doc)
        self.assertIn("PowerContext", doc)


if __name__ == "__main__":
    unittest.main()
