from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apm_bridge.core import create_pack, install_extension, uninstall_extension, validate_pack


class ApmBridgeTests(unittest.TestCase):
    def test_installer_merges_both_harnesses_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_extension(
                hosts=["codex", "claude"], root=root, hooks=True, dry_run=False
            )
            codex = (root / ".codex" / "config.toml").read_text(encoding="utf-8")
            claude = json.loads(
                (root / ".claude.json").read_text(encoding="utf-8")
            )
            claude_hooks = json.loads(
                (root / ".claude" / "settings.json").read_text(encoding="utf-8")
            )

            self.assertIn("[mcp_servers.schift]", codex)
            self.assertIn("@schift-io/ai-memory-mcp", codex)
            self.assertNotIn("SCHIFT_API_KEY =", codex)
            self.assertEqual(claude["mcpServers"]["schift"]["command"], "npx")
            self.assertIn("Stop", claude_hooks["hooks"])

            uninstall_extension(hosts=["codex", "claude"], root=root, purge_local_data=False)
            self.assertNotIn("BEGIN SCHIFT EXTENSION", (root / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertNotIn("schift", json.loads((root / ".claude.json").read_text(encoding="utf-8")).get("mcpServers", {}))

    def test_imported_skill_becomes_a_valid_local_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "# Customer brief\n\nUse only cited company evidence.", encoding="utf-8"
            )
            pack = create_pack(
                destination=root / "workspace",
                name="customer-brief",
                purpose="고객 브리프를 근거와 함께 정리한다.",
                model="openai/gpt-5.4-mini",
                connectors=["schift-memory", "schift-write", "local-model"],
                source=source,
            )
            result = validate_pack(pack)

            self.assertTrue(result.ok, result.messages)
            self.assertIsNotNone(result.artifact)
            self.assertTrue(result.artifact.is_file())
            self.assertTrue(
                (pack / "runtime" / "codex" / ".codex-plugin" / "plugin.json").is_file()
            )
            self.assertTrue(
                (pack / "runtime" / "claude" / ".claude-plugin" / "plugin.json").is_file()
            )
            manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
            self.assertIn("memory_write", manifest["approval_required_for"])
            self.assertEqual(manifest["agents_md_ref"], "agent.md")
            self.assertTrue(manifest["primary_skill_id"])


if __name__ == "__main__":
    unittest.main()
