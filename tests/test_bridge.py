from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apm_bridge.core import (
    create_pack,
    deploy_pack,
    install_extension,
    undeploy_pack,
    uninstall_extension,
    validate_pack,
    verify_deployment,
)
from apm_bridge.studio import resolve_generated_manifest, stage_dropped_source


class ApmBridgeTests(unittest.TestCase):
    def test_deploy_installs_claude_and_codex_server_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "# Evidence brief\n\nUse Schift evidence and cite it.", encoding="utf-8"
            )
            env_file = root / ".env.local"
            env_file.write_text(
                "SCHIFT_API_URL=https://api.example.test\nSCHIFT_API_KEY=sch_test_key\n",
                encoding="utf-8",
            )
            pack = create_pack(
                destination=root / "workspace",
                name="evidence-brief",
                purpose="Prepare a cited evidence brief.",
                model="anthropic/claude-sonnet",
                connectors=["schift-memory", "local-model"],
                source=source,
            )
            with self.assertRaisesRegex(ValueError, "server needs .*config"):
                deploy_pack(
                    pack=pack,
                    hosts=["claude"],
                    root=root / "missing-config-home",
                    hooks=True,
                )
            blocked_skill = root / "blocked-home" / ".claude" / "skills" / "schift-evidence-brief" / "SKILL.md"
            blocked_skill.parent.mkdir(parents=True)
            blocked_skill.write_text("# User-owned skill\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-managed claude skill"):
                deploy_pack(
                    pack=pack,
                    hosts=["claude"],
                    root=root / "blocked-home",
                    hooks=True,
                    env_file=env_file,
                )
            deployed = deploy_pack(
                pack=pack,
                hosts=["claude", "codex"],
                root=root / "server-home",
                hooks=True,
                env_file=env_file,
            )
            server = root / "server-home"
            launcher = server / ".local" / "bin" / "schift-claude-evidence-brief"
            self.assertTrue(deployed.release.is_dir())
            self.assertTrue((server / ".claude" / "skills" / "schift-evidence-brief" / "SKILL.md").is_file())
            self.assertTrue((server / ".codex" / "skills" / "schift-evidence-brief" / "SKILL.md").is_file())
            self.assertTrue(launcher.is_file())
            self.assertIn("--mcp-config", launcher.read_text(encoding="utf-8"))
            self.assertIn("--append-system-prompt", launcher.read_text(encoding="utf-8"))
            verification = verify_deployment(
                agent_id="evidence-brief", hosts=["claude", "codex"], root=server
            )
            self.assertTrue(verification.ok, verification.messages)
            undeploy_pack(agent_id="evidence-brief", hosts=["claude", "codex"], root=server)
            self.assertFalse((server / ".schift-extension" / "packs" / "evidence-brief").exists())
            self.assertFalse(launcher.exists())

    def test_mcp_upload_only_accepts_generated_pack_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "workspace"
            pack = output / "sample.agent"
            pack.mkdir(parents=True)
            manifest = pack / "pack.json"
            manifest.write_text("{}\n", encoding="utf-8")
            self.assertEqual(
                resolve_generated_manifest(destination=output, value=str(manifest)), manifest.resolve()
            )
            self.assertEqual(
                resolve_generated_manifest(destination=output, value=str(pack)), manifest.resolve()
            )
            with self.assertRaises(ValueError):
                resolve_generated_manifest(destination=output, value=str(pack / "agent.md"))

    def test_dropped_markdown_source_is_staged_for_pack_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = stage_dropped_source(
                destination=Path(tmp),
                name="SKILL.md",
                content="# Contract review\n\nUse cited evidence only.\n",
            )
            self.assertTrue(source.is_file())
            self.assertEqual(source.parent.name, ".studio-imports")
            self.assertEqual(source.read_text(encoding="utf-8"), "# Contract review\n\nUse cited evidence only.\n")

    def test_installer_provisions_private_env_config_without_host_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env.local"
            env_file.write_text("SCHIFT_API_URL=https://api.example.test\nSCHIFT_API_KEY=sch_test_key\nSCHIFT_BUCKET_ID=stale-id\n", encoding="utf-8")
            install_extension(hosts=["codex"], root=root, hooks=True, dry_run=False, env_file=env_file)
            config = json.loads((root / ".schift" / "ai-memory" / "config.json").read_text(encoding="utf-8"))
            host_config = (root / ".codex" / "config.toml").read_text(encoding="utf-8")
            self.assertEqual(config["api_base_url"], "https://api.example.test")
            self.assertEqual(config["api_key"], "sch_test_key")
            self.assertEqual(config["bucket"], "default")
            self.assertNotIn("sch_test_key", host_config)

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
            self.assertIn("@schift-io/mcp", codex)
            self.assertNotIn("SCHIFT_API_KEY =", codex)
            self.assertEqual(claude["mcpServers"]["schift"]["command"], "npx")
            self.assertIn("Stop", claude_hooks["hooks"])

            uninstall_extension(hosts=["codex", "claude"], root=root, purge_local_data=False)
            self.assertNotIn("BEGIN SCHIFT EXTENSION", (root / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertNotIn("schift", json.loads((root / ".claude.json").read_text(encoding="utf-8")).get("mcpServers", {}))

    def test_installer_upgrades_and_removes_legacy_claude_mcp_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".claude.json").write_text(
                json.dumps({"mcpServers": {"schift": {"command": "npx", "args": ["-y", "@schift-io/ai-memory-mcp"]}}}),
                encoding="utf-8",
            )
            install_extension(hosts=["claude"], root=root, hooks=False, dry_run=False)
            config = json.loads((root / ".claude.json").read_text(encoding="utf-8"))
            self.assertEqual(config["mcpServers"]["schift"]["args"], ["-y", "@schift-io/mcp"])
            uninstall_extension(hosts=["claude"], root=root, purge_local_data=False)
            config = json.loads((root / ".claude.json").read_text(encoding="utf-8"))
            self.assertNotIn("schift", config.get("mcpServers", {}))

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
