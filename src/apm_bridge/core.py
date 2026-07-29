from __future__ import annotations

import json
import re
import gzip
import io
import shutil
import tarfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "https://mcp.schift.io/mcp"

CONNECTORS: dict[str, dict[str, Any]] = {
    "schift-memory": {
        "label": "Schift Memory",
        "description": "회사 메모리를 검색하고 근거를 가져옵니다.",
        "capabilities": ["auth", "tenant_core_memory_query"],
        "mcp_tools": ["schift_search", "schift_recall"],
    },
    "schift-write": {
        "label": "Schift write-back",
        "description": "승인된 사실과 문서를 Schift에 저장합니다.",
        "capabilities": ["auth", "source_upload_storage"],
        "mcp_tools": ["memory_write", "document_ingest"],
    },
    "local-model": {
        "label": "내 구독 모델",
        "description": "Claude 또는 Codex가 모델 실행을 맡습니다.",
        "capabilities": ["text_generation_connector"],
        "mcp_tools": [],
    },
}


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    messages: list[str]
    artifact: Path | None = None


def _quote_yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not normalized:
        raise ValueError("name must contain at least one letter or number")
    return normalized


def _read_source(source: Path) -> tuple[str, str]:
    if source.is_file():
        return source.stem, source.read_text(encoding="utf-8")
    for candidate in ("SKILL.md", "AGENTS.md", "agent.md"):
        path = source / candidate
        if path.is_file():
            return source.name, path.read_text(encoding="utf-8")
    raise ValueError(f"no SKILL.md, AGENTS.md, or agent.md found in {source}")


def _runtime_contract(connectors: list[str], endpoint: str) -> dict[str, Any]:
    selected = [name for name in connectors if name in CONNECTORS]
    tools = sorted(
        {
            tool
            for connector in selected
            for tool in CONNECTORS[connector]["mcp_tools"]
        }
    )
    return {
        "schema_version": 1,
        "purpose": "Local BYO runtime for Codex and Claude",
        "model_execution": "host_subscription",
        "mcp": {
            "name": "schift",
            "url": endpoint,
            "tools": tools,
            "credential": "SCHIFT_API_KEY inherited from host environment",
        },
        "connectors": selected,
        "hook_policy": {
            "enabled_by_default": False,
            "data": "summary_metadata_only",
            "failure_mode": "local queue only; never block the host session",
        },
    }


def _native_mcp_config() -> dict[str, Any]:
    return {
        "mcpServers": {
            "schift": {
                "command": "npx",
                "args": ["-y", "@schift-io/ai-memory-mcp"],
            }
        }
    }


def _write_native_projection(pack: Path, skill_name: str, skill_text: str) -> None:
    for host, manifest_dir in (("codex", ".codex-plugin"), ("claude", ".claude-plugin")):
        root = pack / "runtime" / host
        (root / manifest_dir).mkdir(parents=True)
        (root / "skills" / skill_name).mkdir(parents=True)
        (root / "skills" / skill_name / "SKILL.md").write_text(
            skill_text, encoding="utf-8"
        )
        (root / manifest_dir / "plugin.json").write_text(
            json.dumps(
                {
                    "name": f"schift-extension-{pack.stem.removesuffix('.agent')}",
                    "version": "0.1.0",
                    "description": "Generated local projection of a Schift APM pack.",
                    "skills": "./skills",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (root / ".mcp.json").write_text(
            json.dumps(_native_mcp_config(), indent=2) + "\n", encoding="utf-8"
        )


def _required_capabilities(connectors: list[str]) -> list[str]:
    return sorted(
        {
            capability
            for connector in connectors
            for capability in CONNECTORS.get(connector, {}).get("capabilities", [])
        }
    )


def _apm_yaml(
    *, name: str, purpose: str, version: str, skills: list[str], connectors: list[str]
) -> str:
    capabilities = _required_capabilities(connectors)
    skill_lines = "\n".join(
        f"  - id: schift/skills/{skill}\n    path: skills/{skill}/SKILL.md"
        for skill in skills
    )
    capability_lines = "\n".join(f"    - {capability}" for capability in capabilities)
    return (
        f"name: {name}\n"
        f"display_name: {_quote_yaml(name.replace('-', ' ').title())}\n"
        f"version: {version}\n"
        f"description: {_quote_yaml(purpose)}\n"
        "pipeline: react\n"
        "access_scope: org\n"
        "agents:\n"
        f"  - id: schift/{name}/agent.md\n"
        "    path: agent.md\n"
        "skills:\n"
        f"{skill_lines}\n"
        "runtime_boundary:\n"
        "  host_services_only:\n"
        f"{capability_lines or '    []'}\n"
    )


def create_pack(
    *,
    destination: Path,
    name: str,
    purpose: str,
    model: str,
    connectors: list[str],
    source: Path | None = None,
    endpoint: str = DEFAULT_ENDPOINT,
) -> Path:
    safe_name = _safe_name(name)
    unknown = sorted(set(connectors) - set(CONNECTORS))
    if unknown:
        raise ValueError(f"unknown connector(s): {', '.join(unknown)}")
    pack = destination.resolve() / f"{safe_name}.agent"
    if pack.exists():
        raise ValueError(f"refusing to overwrite existing pack: {pack}")
    pack.mkdir(parents=True)

    source_title = "Structured APM authoring"
    source_text = (
        "# APM Authoring Agent\n\n"
        "Use the selected skills and Schift tools only for the declared purpose.\n"
        "Do not write data outside explicit user approval.\n"
    )
    if source is not None:
        source_title, source_text = _read_source(source.resolve())

    skill_name = _safe_name(source_title)
    (pack / "skills" / skill_name).mkdir(parents=True)
    (pack / "agent.md").write_text(source_text, encoding="utf-8")
    (pack / "skills" / skill_name / "SKILL.md").write_text(
        source_text if source_text.startswith("#") else f"# {source_title}\n\n{source_text}",
        encoding="utf-8",
    )

    runtime = _runtime_contract(connectors, endpoint)
    manifest = {
        "schema_version": 1,
        "agent_id": safe_name,
        "package_ref": f"{safe_name}@0.1.0",
        "name": safe_name.replace("-", " ").title(),
        "agents_md_ref": "agent.md",
        "agents_md_content": source_text,
        "primary_skill_id": f"schift/skills/{skill_name}",
        "purpose": purpose,
        "model_policy": {
            "execution": "host_subscription",
            "default": model,
            "provider_lock": False,
        },
        "skills": [
            {
                "id": f"schift/skills/{skill_name}",
                "path": f"skills/{skill_name}/SKILL.md",
                "source": "imported" if source else "scaffolded",
            }
        ],
        "mcp_servers": [runtime["mcp"]],
        "connectors": runtime["connectors"],
        "runtime_boundary": {
            "host_services_only": _required_capabilities(connectors)
        },
        "approval_required_for": (
            ["memory_write", "document_ingest"] if "schift-write" in connectors else []
        ),
    }
    (pack / "pack.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (pack / "runtime").mkdir()
    (pack / "runtime" / "bridge.json").write_text(
        json.dumps(runtime, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _write_native_projection(
        pack,
        skill_name,
        (pack / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8"),
    )
    (pack / "apm.yml").write_text(
        _apm_yaml(
            name=safe_name,
            purpose=purpose,
            version="0.1.0",
            skills=[skill_name],
            connectors=connectors,
        ),
        encoding="utf-8",
    )
    return pack


def _load_capabilities() -> tuple[set[str], set[str]]:
    return {
        "auth", "tenant_core_memory_query", "source_upload_storage",
        "text_generation_connector",
    }, {"usage_ledger", "credit_metering", "render_worker", "stitch_worker", "connector_handoff", "higgsfield_mcp"}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _content_hash(manifest: dict[str, Any], files: dict[str, bytes]) -> str:
    excluded = {"schema_version", "router_enabled", "router_topic_hints", "router_shortcut_keywords", "router_slash_commands", "router_requires_attachment", "router_scope", "router_session_scope", "router_min_confidence", "router_description", "router_default_handler", "hub_label", "hub_role", "hub_inputs", "hub_output", "hub_review", "intake_question", "intake_options", "feature_flag", "hidden", "owner_org_id"}
    digest = sha256()
    digest.update(b"apm-v1\n")
    digest.update(sha256(_canonical_json({key: value for key, value in manifest.items() if key not in excluded})).hexdigest().encode())
    digest.update(b"\n")
    for name in sorted(files):
        digest.update(name.encode()); digest.update(b"\0"); digest.update(sha256(files[name]).hexdigest().encode()); digest.update(b"\n")
    return digest.hexdigest()


def _build_apm_bundle(manifest: dict[str, Any], files: dict[str, bytes]) -> tuple[bytes, str]:
    content_hash = _content_hash(manifest, files)
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            for name, data in sorted({"manifest.json": _canonical_json(manifest), **files}.items()):
                info = tarfile.TarInfo(name=name); info.size = len(data); info.mtime = 0; info.uid = info.gid = 0; info.uname = info.gname = ""; info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
        zipped.write(archive.getvalue())
    return raw.getvalue(), content_hash


def build_pack(pack: Path) -> Path:
    pack = pack.resolve()
    manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
    files = {
        str(path.relative_to(pack)): path.read_bytes()
        for path in sorted(pack.rglob("*"))
        if path.is_file() and "dist" not in path.parts and "__pycache__" not in path.parts
    }
    blob, content_hash = _build_apm_bundle(manifest, files)
    output = pack / "dist"
    output.mkdir(exist_ok=True)
    target = output / f"{manifest['agent_id']}-{manifest['package_ref'].rsplit('@', 1)[1]}.apm"
    target.write_bytes(blob)
    (output / "build.json").write_text(
        json.dumps(
            {
                "artifact": target.name,
                "content_hash": content_hash,
                "size_bytes": len(blob),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def validate_pack(pack: Path, *, build: bool = True) -> ValidationResult:
    pack = pack.resolve()
    messages: list[str] = []
    required_files = ["apm.yml", "pack.json", "agent.md", "runtime/bridge.json"]
    missing = [name for name in required_files if not (pack / name).is_file()]
    if missing:
        return ValidationResult(False, [f"missing required file: {name}" for name in missing])

    try:
        manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
        runtime = json.loads((pack / "runtime" / "bridge.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return ValidationResult(False, [f"invalid JSON: {error}"])

    if not manifest.get("agent_id") or not manifest.get("package_ref"):
        messages.append("pack.json needs agent_id and package_ref")
    if not manifest.get("purpose"):
        messages.append("pack.json needs a user-facing purpose")
    if runtime.get("model_execution") != "host_subscription":
        messages.append("model execution must remain host_subscription for local BYO")
    if runtime.get("mcp", {}).get("name") != "schift":
        messages.append("runtime bridge must declare the Schift MCP server")

    vocabulary, local_excludes = _load_capabilities()
    required = set(manifest.get("runtime_boundary", {}).get("host_services_only", []))
    unknown = sorted(required - vocabulary)
    unsupported = sorted(required & local_excludes)
    if unknown:
        messages.append(f"unknown host capability: {', '.join(unknown)}")
    if unsupported:
        messages.append(
            "not runnable locally because local-byo cannot provide: "
            + ", ".join(unsupported)
        )

    skills = manifest.get("skills", [])
    if not isinstance(skills, list) or not skills:
        messages.append("at least one skill is required")
    else:
        for skill in skills:
            path = pack / str(skill.get("path", ""))
            if not path.is_file():
                messages.append(f"skill source is missing: {path.relative_to(pack)}")

    if messages:
        return ValidationResult(False, messages)
    artifact = build_pack(pack) if build else None
    passed = [
        "required files present",
        "local-byo capability boundary satisfied",
        "Schift MCP contract declared",
        "model execution owned by Claude/Codex subscription",
    ]
    if artifact:
        passed.append(f"sealed artifact built: {artifact}")
    return ValidationResult(True, passed, artifact)


def _merge_marked_toml(text: str, block: str) -> str:
    start = "# BEGIN SCHIFT APM BRIDGE"
    end = "# END SCHIFT APM BRIDGE"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(block.rstrip(), text).rstrip() + "\n"
    suffix = "\n" if text and not text.endswith("\n") else ""
    return text + suffix + "\n" + block.rstrip() + "\n"


def _codex_block() -> str:
    return """# BEGIN SCHIFT APM BRIDGE
[mcp_servers.schift]
command = "npx"
args = ["-y", "@schift-io/mcp"]
startup_timeout_sec = 30
# SCHIFT_API_KEY is inherited from the Codex process; it is never written here.
# END SCHIFT APM BRIDGE"""


def _claude_mcp_config() -> dict[str, Any]:
    return {
        "command": "npx",
        "args": ["-y", "@schift-io/mcp"],
    }


def _claude_hooks() -> dict[str, Any]:
    command = "npx -y @schift-io/ai-memory-hooks claude-stop"
    return {
        "Stop": [{"hooks": [{"type": "command", "command": command, "timeout": 5}]}],
        "SessionEnd": [{"hooks": [{"type": "command", "command": command, "timeout": 5}]}],
    }


def _merge_hook_event(
    existing: dict[str, Any], event: str, definitions: list[dict[str, Any]]
) -> None:
    current = existing.setdefault(event, [])
    if not isinstance(current, list):
        raise ValueError(f"Claude settings hooks.{event} must be an array")
    command = definitions[0]["hooks"][0]["command"]
    if not any(
        command == item.get("hooks", [{}])[0].get("command")
        for item in current
        if isinstance(item, dict)
    ):
        current.extend(definitions)


def install_runtime(
    *,
    hosts: list[str],
    root: Path,
    hooks: bool,
    dry_run: bool,
) -> list[Path]:
    targets: list[Path] = []
    unknown = sorted(set(hosts) - {"codex", "claude"})
    if unknown:
        raise ValueError(f"unknown host(s): {', '.join(unknown)}")
    if "codex" in hosts:
        path = root / ".codex" / "config.toml"
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        merged = _merge_marked_toml(content, _codex_block())
        targets.append(path)
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(merged, encoding="utf-8")
            if hooks:
                hook_path = root / ".codex" / "hooks.json"
                hook_config: dict[str, Any] = {}
                if hook_path.exists():
                    loaded = json.loads(hook_path.read_text(encoding="utf-8"))
                    if not isinstance(loaded, dict):
                        raise ValueError("Codex hooks.json must contain a JSON object")
                    hook_config = loaded
                hook_events = hook_config.setdefault("hooks", {})
                _merge_hook_event(
                    hook_events,
                    "Stop",
                    [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "npx -y @schift-io/ai-memory-hooks codex-stop",
                                }
                            ]
                        }
                    ],
                )
                hook_path.parent.mkdir(parents=True, exist_ok=True)
                hook_path.write_text(
                    json.dumps(hook_config, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                targets.append(hook_path)
    if "claude" in hosts:
        path = root / ".claude.json"
        content: dict[str, Any] = {}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("Claude settings.json must contain a JSON object")
            content = loaded
        content.setdefault("mcpServers", {})["schift"] = _claude_mcp_config()
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(content, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        if hooks:
            hooks_path = root / ".claude" / "settings.json"
            hook_content: dict[str, Any] = {}
            if hooks_path.exists():
                loaded = json.loads(hooks_path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("Claude settings.json must contain a JSON object")
                hook_content = loaded
            hook_config = hook_content.setdefault("hooks", {})
            for event, definitions in _claude_hooks().items():
                _merge_hook_event(hook_config, event, definitions)
            targets.append(hooks_path)
            if not dry_run:
                hooks_path.parent.mkdir(parents=True, exist_ok=True)
                hooks_path.write_text(
                    json.dumps(hook_content, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
        targets.append(path)
    return targets


def capture_event(host: str, payload: str, root: Path) -> Path:
    queue = root / ".schift-extension" / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    target = queue / f"{host}-{digest}.json"
    target.write_text(
        json.dumps(
            {
                "host": host,
                "policy": "summary_metadata_only",
                "payload_sha256": sha256(payload.encode("utf-8")).hexdigest(),
                "payload_bytes": len(payload.encode("utf-8")),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


_MARKER_START = "# BEGIN SCHIFT EXTENSION"
_MARKER_END = "# END SCHIFT EXTENSION"
_MANAGED = "--managed-by=schift-extension"


def _extension_commands(host: str) -> list[tuple[str, str]]:
    if host == "codex":
        return [("SessionStart", f"npx -y @schift-io/ai-memory-hooks codex-session-start {_MANAGED}"), ("Stop", f"npx -y @schift-io/ai-memory-hooks codex-stop {_MANAGED}")]
    return [("Stop", f"npx -y @schift-io/ai-memory-hooks claude-stop {_MANAGED}"), ("SessionEnd", f"npx -y @schift-io/ai-memory-hooks claude-session-end {_MANAGED}")]


def _json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _merge_managed_hook(config: dict[str, Any], event: str, command: str) -> bool:
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be a JSON object")
    definitions = hooks.setdefault(event, [])
    if not isinstance(definitions, list):
        raise ValueError(f"hooks.{event} must be an array")
    if any(isinstance(item, dict) and any(isinstance(hook, dict) and hook.get("command") == command for hook in item.get("hooks", [])) for item in definitions):
        return False
    definitions.append({"hooks": [{"type": "command", "command": command, "timeout": 10}]})
    return True


def _remove_managed_hook(config: dict[str, Any], event: str, command: str) -> bool:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get(event), list):
        return False
    old = hooks[event]
    hooks[event] = [item for item in old if not (isinstance(item, dict) and any(isinstance(hook, dict) and hook.get("command") == command for hook in item.get("hooks", [])))]
    changed = len(old) != len(hooks[event])
    if not hooks[event]:
        del hooks[event]
    if not hooks:
        config.pop("hooks", None)
    return changed


def install_extension(*, hosts: list[str], root: Path, hooks: bool, dry_run: bool) -> list[Path]:
    targets: list[Path] = []
    for host in hosts:
        if host == "codex":
            path = root / ".codex" / "config.toml"
            content = path.read_text(encoding="utf-8") if path.exists() else ""
            block = f"{_MARKER_START}\n[mcp_servers.schift]\ncommand = \"npx\"\nargs = [\"-y\", \"@schift-io/ai-memory-mcp\"]\nstartup_timeout_sec = 30\n# Credentials remain in ~/.schift/ai-memory/config.json.\n{_MARKER_END}"
            pattern = re.compile(re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END), re.DOTALL)
            if not pattern.search(content) and re.search(r"^\[mcp_servers\.schift\]", content, re.MULTILINE):
                raise ValueError("Codex already has a non-managed schift MCP entry")
            next_content = pattern.sub(block, content) if pattern.search(content) else (content.rstrip() + ("\n\n" if content.strip() else "") + block + "\n")
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(next_content, encoding="utf-8")
            targets.append(path)
            if hooks:
                hook_path = root / ".codex" / "hooks.json"; config = _json_object(hook_path)
                if any(_merge_managed_hook(config, event, command) for event, command in _extension_commands(host)) and not dry_run:
                    _write_json(hook_path, config)
                targets.append(hook_path)
        elif host == "claude":
            path = root / ".claude.json"; config = _json_object(path); servers = config.setdefault("mcpServers", {})
            expected = {"command": "npx", "args": ["-y", "@schift-io/ai-memory-mcp"]}
            if not isinstance(servers, dict): raise ValueError("Claude mcpServers must be a JSON object")
            if "schift" in servers and servers["schift"] != expected: raise ValueError("Claude already has a non-managed schift MCP entry")
            servers["schift"] = expected
            if not dry_run: _write_json(path, config)
            targets.append(path)
            if hooks:
                hook_path = root / ".claude" / "settings.json"; hook_config = _json_object(hook_path)
                if any(_merge_managed_hook(hook_config, event, command) for event, command in _extension_commands(host)) and not dry_run:
                    _write_json(hook_path, hook_config)
                targets.append(hook_path)
        else:
            raise ValueError(f"unknown host: {host}")
    return targets


def uninstall_extension(*, hosts: list[str], root: Path, purge_local_data: bool) -> list[Path]:
    targets: list[Path] = []
    for host in hosts:
        if host == "codex":
            path = root / ".codex" / "config.toml"
            if path.exists():
                content = path.read_text(encoding="utf-8")
                next_content = re.sub(r"(?:^|\n)" + re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END) + r"\n?", "", content, flags=re.DOTALL).strip() + "\n"
                if next_content != content: path.write_text(next_content, encoding="utf-8")
            targets.append(path)
            hook_path = root / ".codex" / "hooks.json"; config = _json_object(hook_path)
            if any(_remove_managed_hook(config, event, command) for event, command in _extension_commands(host)): _write_json(hook_path, config)
            targets.append(hook_path)
        elif host == "claude":
            path = root / ".claude.json"; config = _json_object(path); expected = {"command": "npx", "args": ["-y", "@schift-io/ai-memory-mcp"]}
            if isinstance(config.get("mcpServers"), dict) and config["mcpServers"].get("schift") == expected:
                del config["mcpServers"]["schift"]
                if not config["mcpServers"]: del config["mcpServers"]
                _write_json(path, config)
            targets.append(path)
            hook_path = root / ".claude" / "settings.json"; hook_config = _json_object(hook_path)
            if any(_remove_managed_hook(hook_config, event, command) for event, command in _extension_commands(host)): _write_json(hook_path, hook_config)
            targets.append(hook_path)
        else:
            raise ValueError(f"unknown host: {host}")
    if purge_local_data:
        data = root / ".schift" / "ai-memory"; shutil.rmtree(data, ignore_errors=True); targets.append(data)
    return targets
