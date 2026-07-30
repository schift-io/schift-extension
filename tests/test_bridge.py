from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from argparse import Namespace
from base64 import b64decode
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from apm_bridge.core import (
    HostRuntimeAdapter,
    McpRuntimeSpec,
    create_pack,
    deploy_pack,
    install_extension,
    publish_pack,
    undeploy_pack,
    uninstall_extension,
    update_pack,
    validate_pack,
    verify_deployment,
)
from apm_bridge.cli import cmd_studio
from apm_bridge.studio import (
    list_studio_packs,
    publish_pack_via_mcp,
    resolve_generated_manifest,
    stage_dropped_source,
)


class ApmBridgeTests(unittest.TestCase):
    def test_studio_forwards_env_file_to_runtime_install(self) -> None:
        with patch("apm_bridge.studio.run_studio") as run_studio:
            cmd_studio(
                Namespace(
                    host="127.0.0.1",
                    port=8786,
                    output="./apm-workspace",
                    no_open=True,
                    env_file="~/.env.local",
                )
            )
        self.assertEqual(run_studio.call_args.kwargs["env_file"], Path("~/.env.local").expanduser())

    def test_runtime_adapter_is_injected_without_host_specific_branching(self) -> None:
        class FixtureAdapter(HostRuntimeAdapter):
            name = "fixture"

            def __init__(self) -> None:
                self.installed: list[tuple[Path, McpRuntimeSpec]] = []
                self.uninstalled: list[tuple[Path, McpRuntimeSpec]] = []

            def install(self, *, root: Path, runtime: McpRuntimeSpec, hooks: bool, dry_run: bool) -> list[Path]:
                self.installed.append((root, runtime))
                return [root / "fixture-install"]

            def uninstall(self, *, root: Path, runtime: McpRuntimeSpec, purge_local_data: bool) -> list[Path]:
                self.uninstalled.append((root, runtime))
                return [root / "fixture-uninstall"]

            def skill_path(self, root: Path, agent_id: str) -> Path:
                return root / "fixture" / agent_id

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = FixtureAdapter()
            runtime = McpRuntimeSpec(
                server_name="fixture-mcp",
                command="fixture-command",
                args=("serve",),
                legacy_args=(),
            )
            installed = install_extension(
                hosts=["fixture"],
                root=root,
                hooks=False,
                dry_run=False,
                adapters={"fixture": adapter},
                runtime=runtime,
            )
            removed = uninstall_extension(
                hosts=["fixture"],
                root=root,
                purge_local_data=False,
                adapters={"fixture": adapter},
                runtime=runtime,
            )
            self.assertEqual(installed, [root / "fixture-install"])
            self.assertEqual(removed, [root / "fixture-uninstall"])
            self.assertEqual(adapter.installed[0][1].server_name, "fixture-mcp")
            self.assertEqual(adapter.uninstalled[0][1].command, "fixture-command")

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
                "SCHIFT_API_URL=https://api.example.test\nSCHIFT_API_KEY=sch_ingest_key\nSCHIFT_APM_PUBLISH_API_KEY=sch_publish_key\nSCHIFT_DEFAULT_BUCKET_ID=fedcba9876543210fedcba9876543210\nSCHIFT_RAG_BUCKET_ID=0123456789abcdef0123456789abcdef\n",
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

    def test_mcp_publication_only_accepts_generated_pack_manifest(self) -> None:
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

    def test_mcp_publication_passes_generated_agent_directory_to_uploader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "workspace" / "sample.agent"
            pack.mkdir(parents=True)
            (pack / "pack.json").write_text("{}\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"ok": true, "agent_id": "sample", "version": "0.1.0", "is_live": false}\n',
                stderr="",
            )
            with patch("apm_bridge.studio.subprocess.run", return_value=completed) as run:
                publication = publish_pack_via_mcp(pack=pack)
            self.assertEqual(publication["agent_id"], "sample")
            self.assertFalse(publication["is_live"])
            self.assertEqual(run.call_args.args[0][-1], str(pack))

    def test_studio_lists_and_updates_one_pack_without_replacing_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            first = create_pack(
                destination=workspace,
                name="first-pack",
                purpose="Prepare the first brief.",
                model="openai/gpt-5.4-mini",
                connectors=["schift-memory", "local-model"],
            )
            second = create_pack(
                destination=workspace,
                name="second-pack",
                purpose="Prepare the second brief.",
                model="anthropic/claude-sonnet",
                connectors=["schift-memory", "local-model"],
            )

            updated = update_pack(
                pack=first,
                purpose="Store reviewed facts after approval.",
                model="anthropic/claude-sonnet",
                connectors=["schift-memory", "schift-write", "local-model"],
            )
            records = {item["agent_id"]: item for item in list_studio_packs(workspace)}
            manifest = json.loads((updated / "pack.json").read_text(encoding="utf-8"))

            self.assertEqual(updated, first)
            self.assertTrue(validate_pack(updated).ok)
            self.assertTrue(second.is_dir())
            self.assertEqual(records.keys(), {"first-pack", "second-pack"})
            self.assertEqual(records["first-pack"]["model"], "anthropic/claude-sonnet")
            self.assertEqual(manifest["purpose"], "Store reviewed facts after approval.")
            self.assertIn("schift-write", manifest["connectors"])

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
            env_file.write_text("SCHIFT_API_URL=https://api.example.test\nSCHIFT_API_KEY=sch_test_key\nSCHIFT_BUCKET_ID=stale-id\nSCHIFT_DEFAULT_BUCKET_ID=fedcba9876543210fedcba9876543210\nSCHIFT_RAG_BUCKET_ID=0123456789abcdef0123456789abcdef\n", encoding="utf-8")
            install_extension(hosts=["codex"], root=root, hooks=True, dry_run=False, env_file=env_file)
            config = json.loads((root / ".schift" / "ai-memory" / "config.json").read_text(encoding="utf-8"))
            host_config = (root / ".codex" / "config.toml").read_text(encoding="utf-8")
            self.assertEqual(config["api_base_url"], "https://api.example.test")
            self.assertEqual(config["api_key"], "sch_test_key")
            self.assertEqual(config["bucket"], "default")
            self.assertEqual(config["session_bucket_id"], "0123456789abcdef0123456789abcdef")
            self.assertEqual(config["bucket_id"], "fedcba9876543210fedcba9876543210")
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
            self.assertIn("NODE_OPTIONS", codex)
            self.assertNotIn("SCHIFT_API_KEY =", codex)
            self.assertEqual(claude["mcpServers"]["schift"]["command"], "npx")
            self.assertEqual(claude["mcpServers"]["schift"]["env"]["NODE_OPTIONS"], "--dns-result-order=ipv4first")
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
            self.assertEqual(
                config["mcpServers"]["schift"]["args"],
                ["--yes", "--package=@schift-io/mcp", "schift-mcp"],
            )
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
            self.assertEqual(manifest["mcp_servers"][0]["name"], "schift-rag")

    def test_publish_binds_a_sealed_pack_to_the_authenticated_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = create_pack(
                destination=root / "workspace",
                name="owned-brief",
                purpose="Prepare an owned registry proof.",
                model="openai/gpt-5.4-mini",
                connectors=["schift-memory", "local-model"],
            )
            env_file = root / ".env.local"
            env_file.write_text(
                "SCHIFT_API_URL=https://api.example.test\nSCHIFT_API_KEY=sch_ingest_key\nSCHIFT_APM_PUBLISH_API_KEY=sch_publish_key\n",
                encoding="utf-8",
            )
            calls: list[dict] = []

            def fake_request(**kwargs):
                calls.append(kwargs)
                if kwargs["method"] == "POST":
                    body = kwargs["body"]
                    self.assertEqual(body["make_live"], False)
                    self.assertEqual(body["visibility"], "private")
                    self.assertEqual(body["allowed_orgs"], ["room821"])
                    self.assertTrue(b64decode(body["apm_b64"]))
                    self.assertEqual(kwargs["api_key"], "sch_publish_key")
                    return {
                        "ok": True,
                        "ref": {
                            "agent_id": "owned-brief",
                            "version": "0.1.0",
                            "content_hash": body["expected_hash"],
                            "owner_org": "room821",
                            "uploaded_by": "usr_owner",
                            "is_live": False,
                        },
                    }
                return {
                    "packs": [
                        {
                            "agent_id": "owned-brief",
                            "owner_org": "room821",
                            "uploaded_by": "usr_owner",
                        }
                    ]
                }

            with patch("apm_bridge.core._api_json_request", side_effect=fake_request):
                result = publish_pack(
                    pack=pack,
                    root=root,
                    env_file=env_file,
                    allowed_orgs=["room821"],
                )

            self.assertEqual(result.agent_id, "owned-brief")
            self.assertEqual(result.owner_org, "room821")
            self.assertEqual(result.uploaded_by, "usr_owner")
            self.assertFalse(result.is_live)
            self.assertEqual([call["method"] for call in calls], ["POST", "GET"])

    def test_registry_request_retries_transient_failure(self) -> None:
        from apm_bridge.core import _api_json_request

        class SuccessResponse:
            def read(self) -> bytes:
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback) -> None:
                return None

        transient = HTTPError(
            "https://api.example.test/v1/apm/registry/packs/upload",
            500,
            "internal server error",
            hdrs=None,
            fp=BytesIO(b'{"message":"temporary"}'),
        )
        with (
            patch("apm_bridge.core.urlopen", side_effect=[transient, SuccessResponse()]) as request,
            patch("apm_bridge.core.time.sleep") as sleep,
        ):
            result = _api_json_request(
                method="POST",
                url="https://api.example.test/v1/apm/registry/packs/upload",
                api_key="publish-key",
                body={"apm_b64": "bytes"},
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(0.5)


if __name__ == "__main__":
    unittest.main()
