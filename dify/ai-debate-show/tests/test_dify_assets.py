"""《再说一遍？》Dify 交付资产的完整性测试。

**这些测试只检查交付物本身**：DSL 文件是否可读、结构字段是否齐全、三份提示词是否与
DSL 逐字一致、文档章节是否齐备、文件里有没有混进凭据。

它们**不能替代真实的 Dify 导入验证**。测试通过只代表「交付资产是完整且自洽的」；
真实导入与运行证据由 ``evidence/dify-e2e.md`` 记录。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parents[1] / "dify"
DSL_PATH = ASSET_DIR / "ai-debate-show-chatflow.yml"
PROMPTS_PATH = ASSET_DIR / "PROMPTS.md"
IMPORT_PATH = ASSET_DIR / "DIFY_IMPORT.md"

# 提示词在 DSL 里以块标量（block scalar）存放，缩进由 YAML 嵌套层级决定。
# 逐字一致性检查不写死缩进，而是遍历可能的缩进宽度。
_MAX_BLOCK_INDENT = 24


def _read_text(path: Path) -> str:
    """按 UTF-8 读取交付资产；存在 BOM 时直接失败。"""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise AssertionError(f"{path.name} 不应带 UTF-8 BOM")
    return raw.decode("utf-8")


def _fenced_blocks(text: str) -> list[str]:
    """取出 Markdown 里所有围栏代码块的内容。"""
    blocks: list[str] = []
    pattern = re.compile(r"```[a-zA-Z0-9_-]*\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(text):
        blocks.append(match.group(1).rstrip("\n"))
    return blocks


def _section(text: str, heading: str) -> str:
    """取出某个二级标题到下一个二级标题之间的正文。

    围栏代码块内部可能出现以 ``## `` 开头的行（提示词自己的小标题），
    因此要先跟踪围栏状态再判断章节边界。
    """
    lines = text.split("\n")
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading.strip():
            start = index
            break
    if start is None:
        raise AssertionError(f"文档里找不到标题 {heading!r}")

    collected: list[str] = []
    in_fence = False
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            collected.append(line)
            continue
        if not in_fence and stripped.startswith("## "):
            break
        collected.append(line)
    return "\n".join(collected)


def _appears_as_yaml_block(yaml_text: str, block: str) -> bool:
    """判断一段文本是否以某种缩进完整出现在 YAML 文本里。

    YAML 块标量里的空行是真正的空行（不带缩进），所以空行不能加前缀。
    """
    lines = block.split("\n")
    for indent in range(_MAX_BLOCK_INDENT):
        candidate = "\n".join((" " * indent + line) if line else "" for line in lines)
        if candidate in yaml_text:
            return True
    return False


class DifyDslAssetTest(unittest.TestCase):
    """DSL 文件本身的可读性与结构。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dsl = _read_text(DSL_PATH)
        cls.prompts = _read_text(PROMPTS_PATH)
        cls.import_doc = _read_text(IMPORT_PATH)

    def test_dsl_files_exist_and_are_utf8(self) -> None:
        for path in (DSL_PATH, PROMPTS_PATH, IMPORT_PATH):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), f"{path.name} 不存在")
                self.assertGreater(path.stat().st_size, 0, f"{path.name} 是空文件")

    def test_dsl_uses_lf_endings_and_no_trailing_whitespace(self) -> None:
        raw = DSL_PATH.read_bytes()
        self.assertNotIn(b"\r\n", raw, "DSL 不应包含 CRLF 换行")
        for number, line in enumerate(self.dsl.split("\n"), start=1):
            self.assertEqual(
                line,
                line.rstrip(),
                f"DSL 第 {number} 行有行尾空白",
            )

    def test_declares_advanced_chat_app(self) -> None:
        self.assertIn("kind: app", self.dsl)
        self.assertIn("mode: advanced-chat", self.dsl)
        self.assertIn("再说一遍？AI 记仇辩论夜", self.dsl)
        self.assertRegex(self.dsl, r'(?m)^version: "\d+\.\d+\.\d+"$')

    def test_contains_required_node_types(self) -> None:
        for node_type in (
            "type: start",
            "type: http-request",
            "type: if-else",
            "type: llm",
            "type: answer",
            "type: assigner",
            "type: code",
        ):
            with self.subTest(node_type=node_type):
                self.assertIn(node_type, self.dsl)
        self.assertIn("Variable Assigner", self.dsl)

    def test_contains_three_arena_paths(self) -> None:
        self.assertIn('"{{#code_session.arena_base#}}/games"', self.dsl)
        self.assertIn(
            '"{{#code_session.arena_base#}}/games/{{#conversation.game_id#}}/rounds"',
            self.dsl,
        )
        self.assertIn(
            '"{{#code_session.arena_base#}}/games/{{#conversation.game_id#}}/memory"',
            self.dsl,
        )

    def test_http_urls_are_built_from_arena_base_url(self) -> None:
        """HTTP 节点的 URL 必须由 arena_base_url 拼出来，不能写死地址。"""
        urls = re.findall(r"^\s*url:\s*(.+)$", self.dsl, re.MULTILINE)
        self.assertEqual(len(urls), 3, "应当正好有三个 HTTP 节点的 URL")
        for url in urls:
            with self.subTest(url=url):
                self.assertIn("{{#code_session.arena_base#}}", url)
                self.assertNotIn("http://", url)
                self.assertNotIn("https://", url)

    def test_uses_arena_contract_fields(self) -> None:
        for field in (
            "card_reused",
            "memory_status",
            "memory_candidate",
            "game_finished",
            "opponent_message",
            "follow_up_question",
            "selected_card_id",
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.dsl)

    def test_http_nodes_declare_timeout_and_error_branch(self) -> None:
        self.assertIn("connect: 10", self.dsl)
        self.assertIn("read: 60", self.dsl)
        self.assertIn("write: 30", self.dsl)
        self.assertIn("error_strategy: fail-branch", self.dsl)
        self.assertIn("sourceHandle: fail-branch", self.dsl)
        self.assertIn("retry_enabled: false", self.dsl)

    def test_creative_model_nodes_have_room_for_a_final_answer(self) -> None:
        """回合和结算节点不能把 token 全耗在推演里而没有最终玩家可见文本。"""
        self.assertEqual(self.dsl.count("max_tokens: 4096"), 2)

    def test_http_json_bodies_use_one_complete_json_template(self) -> None:
        """Dify 1.17 的 JSON body 执行器要求每个请求节点恰好一个 body item。"""
        expected = (
            "id: body-create-game-json",
            "id: body-round-json",
            "id: body-memory-json",
        )
        for marker in expected:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.dsl)
        self.assertNotIn("id: body-game-id", self.dsl)
        self.assertNotIn("id: body-player-action", self.dsl)
        self.assertNotIn("id: body-memory-player-message", self.dsl)
        self.assertEqual(self.dsl.count('key: ""'), 3)

    def test_settlement_default_value_is_a_json_string(self) -> None:
        """Assigner/LLM 默认值必须是字符串，不能被 YAML 解析成对象。"""
        self.assertIn(
            'value: \'{"settlement_text":"【本局结算】三回合结束，本局收工。"}\'',
            self.dsl,
        )

    def test_http_nodes_send_no_authorization_header(self) -> None:
        """Arena 到 PowerContext 的认证在服务端完成，DSL 不得带认证头。"""
        self.assertIn("type: no-auth", self.dsl)
        self.assertNotIn("Authorization", self.dsl)
        self.assertNotIn("Bearer", self.dsl)

    def test_contains_no_obvious_real_credentials(self) -> None:
        patterns = (
            r"sk-[A-Za-z0-9]{16,}",
            r"sk-ant-[A-Za-z0-9_\-]{16,}",
            r"AKIA[0-9A-Z]{16}",
            r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
            r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}",
        )
        for name, text in (
            ("DSL", self.dsl),
            ("PROMPTS.md", self.prompts),
            ("DIFY_IMPORT.md", self.import_doc),
        ):
            for pattern in patterns:
                with self.subTest(asset=name, pattern=pattern):
                    self.assertIsNone(
                        re.search(pattern, text),
                        f"{name} 里出现了疑似真实凭据：{pattern}",
                    )

    def test_start_node_collects_required_inputs(self) -> None:
        for variable in (
            "arena_base_url",
            "scope_id",
            "player_nickname",
            "topic_id",
            "initial_stance",
            "opponent_id",
            "player_action",
            "game_id_fallback",
        ):
            with self.subTest(variable=variable):
                self.assertIn(f"variable: {variable}", self.dsl)
        for action in ("double_down", "switch_explain", "wild_card", "free_input"):
            with self.subTest(action=action):
                self.assertIn(f"- {action}", self.dsl)

    def test_declares_conversation_variables(self) -> None:
        self.assertIn("conversation_variables:", self.dsl)
        for name in (
            "round_number",
            "game_finished",
            "game_id",
            "memory_status",
            "memory_context",
            "topic_title",
            "degraded_line",
        ):
            with self.subTest(name=name):
                self.assertIn(f"name: {name}", self.dsl)


class PromptsAssetTest(unittest.TestCase):
    """PROMPTS.md 与 DSL 的一致性。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dsl = _read_text(DSL_PATH)
        cls.prompts = _read_text(PROMPTS_PATH)

    def test_prompts_md_has_three_prompt_sections(self) -> None:
        for heading in (
            "## 提示词一：主持人与对手回合导演",
            "## 提示词二：第三回合综艺结算",
            "## 提示词三：降级话术",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.prompts)

    def test_each_prompt_is_verbatim_in_dsl(self) -> None:
        """三份提示词必须与 DSL 中对应的 prompt_template 逐字一致。"""
        headings = (
            "## 提示词一：主持人与对手回合导演",
            "## 提示词二：第三回合综艺结算",
            "## 提示词三：降级话术",
        )
        checked = 0
        for heading in headings:
            section = _section(self.prompts, heading)
            blocks = _fenced_blocks(section)
            self.assertTrue(blocks, f"{heading} 下面没有围栏代码块")
            block = blocks[-1]
            with self.subTest(heading=heading):
                self.assertTrue(
                    _appears_as_yaml_block(self.dsl, block),
                    f"{heading} 的提示词与 DSL 中的 prompt_template 不一致",
                )
            checked += 1
        self.assertEqual(checked, 3)

    def test_prompt_files_have_no_trailing_whitespace(self) -> None:
        for number, line in enumerate(self.prompts.split("\n"), start=1):
            self.assertEqual(line, line.rstrip(), f"PROMPTS.md 第 {number} 行有行尾空白")


class ImportGuideTest(unittest.TestCase):
    """DIFY_IMPORT.md 的章节完整性。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.import_doc = _read_text(IMPORT_PATH)

    def test_contains_required_sections(self) -> None:
        for keyword in (
            "导入",
            "重新绑定的模型",
            "POWERCONTEXT_BASE_URL",
            "三回合",
            "已知限制",
        ):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, self.import_doc)

    def test_documents_version_basis_and_real_dify_smoke_result(self) -> None:
        self.assertIn("0.6.0", self.import_doc)
        self.assertIn("0.7.0", self.import_doc)
        self.assertIn("langgenius/dify", self.import_doc)
        self.assertIn("Dify 1.17.1", self.import_doc)

    def test_documents_degradation_and_in_memory_sessions(self) -> None:
        self.assertIn("degraded", self.import_doc)
        self.assertIn("本局档案暂未入库", self.import_doc)
        self.assertIn("内存", self.import_doc)

    def test_states_that_real_smoke_is_not_full_memory_e2e(self) -> None:
        """文档必须区分已跑通的降级路径与尚待复核的跨会话路径。"""
        self.assertIn("可信 Scope", self.import_doc)


if __name__ == "__main__":
    unittest.main()
