#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))

from apm_bridge.core import (  # noqa: E402
    CONNECTORS,
    create_pack,
    deploy_pack,
    install_extension,
    ship_pack,
    undeploy_pack,
    uninstall_extension,
    validate_pack,
    verify_deployment,
)


def _hosts(value: str) -> list[str]:
    return ["codex", "claude"] if value == "both" else [value]


def cmd_install(args: argparse.Namespace) -> int:
    targets = install_extension(
        hosts=_hosts(args.host),
        root=Path(args.root).expanduser(),
        hooks=args.hooks,
        dry_run=args.dry_run,
        env_file=Path(args.env_file).expanduser() if args.env_file else None,
    )
    action = "would update" if args.dry_run else "updated"
    for target in targets:
        print(f"{action}: {target}")
    if args.env_file:
        print("Schift credentials were written only to ~/.schift/ai-memory/config.json, never host config.")
    else:
        print("Schift Extension installed. Run with --env-file .env.local or login to configure local credentials.")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    for target in uninstall_extension(hosts=_hosts(args.host), root=Path(args.root).expanduser(), purge_local_data=args.purge_local_data):
        print(f"removed managed entries: {target}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    pack = create_pack(
        destination=Path(args.output).expanduser(),
        name=args.name,
        purpose=args.purpose,
        model=args.model,
        connectors=args.connector,
        source=Path(args.source).expanduser(),
        endpoint=args.endpoint,
    )
    result = validate_pack(pack)
    print(f"created: {pack}")
    for message in result.messages:
        print(f"{'OK' if result.ok else 'ERROR'}: {message}")
    return 0 if result.ok else 1


def cmd_new(args: argparse.Namespace) -> int:
    pack = create_pack(
        destination=Path(args.output).expanduser(),
        name=args.name,
        purpose=args.purpose,
        model=args.model,
        connectors=args.connector,
        endpoint=args.endpoint,
    )
    print(f"created: {pack}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    result = validate_pack(Path(args.pack).expanduser())
    for message in result.messages:
        print(f"{'OK' if result.ok else 'ERROR'}: {message}")
    return 0 if result.ok else 1


def cmd_build(args: argparse.Namespace) -> int:
    result = validate_pack(Path(args.pack).expanduser())
    if not result.ok:
        for message in result.messages:
            print(f"ERROR: {message}")
        return 1
    print(result.artifact)
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    result = deploy_pack(
        pack=Path(args.pack).expanduser(),
        hosts=_hosts(args.host),
        root=Path(args.root).expanduser(),
        hooks=args.hooks,
        env_file=Path(args.env_file).expanduser() if args.env_file else None,
        bin_dir=Path(args.bin_dir).expanduser() if args.bin_dir else None,
        dry_run=args.dry_run,
    )
    print(f"deployed: {result.agent_id}")
    print(f"release: {result.release}")
    print(f"artifact: {result.artifact}")
    for target in result.targets:
        print(f"installed: {target}")
    return 0


def cmd_verify_deploy(args: argparse.Namespace) -> int:
    result = verify_deployment(
        agent_id=args.agent_id,
        hosts=_hosts(args.host),
        root=Path(args.root).expanduser(),
        bin_dir=Path(args.bin_dir).expanduser() if args.bin_dir else None,
    )
    for message in result.messages:
        print(f"{'OK' if result.ok else 'ERROR'}: {message}")
    return 0 if result.ok else 1


def cmd_undeploy(args: argparse.Namespace) -> int:
    for target in undeploy_pack(
        agent_id=args.agent_id,
        hosts=_hosts(args.host),
        root=Path(args.root).expanduser(),
        bin_dir=Path(args.bin_dir).expanduser() if args.bin_dir else None,
    ):
        print(f"removed: {target}")
    return 0


def cmd_ship(args: argparse.Namespace) -> int:
    for line in ship_pack(
        pack=Path(args.pack).expanduser(),
        hosts=_hosts(args.host),
        target=args.target,
        remote_root=args.remote_root,
        remote_bin_dir=args.remote_bin_dir,
        copy_env=args.copy_env,
        env_file=Path(args.env_file).expanduser() if args.env_file else None,
    ):
        print(line)
    return 0


def cmd_catalog(_: argparse.Namespace) -> int:
    print(json.dumps(CONNECTORS, ensure_ascii=False, indent=2))
    return 0


def cmd_studio(args: argparse.Namespace) -> int:
    from apm_bridge.studio import run_studio

    run_studio(
        host=args.host,
        port=args.port,
        output=Path(args.output).expanduser(),
        open_browser=not args.no_open,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schift-extension",
        description="Install the Schift Extension into Claude/Codex and author local APM packs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", aliases=["init"], help="install managed Connector and lifecycle hooks")
    install.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    install.add_argument("--root", default="~")
    install.add_argument("--hooks", action="store_true", default=True)
    install.add_argument("--env-file", help="copy SCHIFT_API_URL and SCHIFT_API_KEY into the private Schift local config")
    install.add_argument("--dry-run", action="store_true")
    install.set_defaults(func=cmd_install)
    uninstall = sub.add_parser("uninstall", help="remove only entries managed by Schift Extension")
    uninstall.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    uninstall.add_argument("--root", default="~")
    uninstall.add_argument("--purge-local-data", action="store_true")
    uninstall.set_defaults(func=cmd_uninstall)

    def author_args(command: argparse.ArgumentParser, *, import_source: bool) -> None:
        if import_source:
            command.add_argument("--source", required=True)
        command.add_argument("--name", required=True)
        command.add_argument("--purpose", required=True)
        command.add_argument("--model", default="openai/gpt-5.4-mini")
        command.add_argument(
            "--connector",
            action="append",
            default=["schift-memory", "local-model"],
            choices=sorted(CONNECTORS),
        )
        command.add_argument("--endpoint", default="https://mcp.schift.io/mcp")
        command.add_argument("--output", default="./apm-workspace")

    imported = sub.add_parser("import", help="convert an existing Skill or agent instruction")
    author_args(imported, import_source=True)
    imported.set_defaults(func=cmd_import)
    new = sub.add_parser("new", help="create a structured APM pack from scratch")
    author_args(new, import_source=False)
    new.set_defaults(func=cmd_new)

    verify = sub.add_parser("verify", help="check the local host boundary and build an artifact")
    verify.add_argument("pack")
    verify.set_defaults(func=cmd_verify)
    build = sub.add_parser("build", help="build a deterministic local .apm artifact")
    build.add_argument("pack")
    build.set_defaults(func=cmd_build)

    deploy = sub.add_parser("deploy", help="install a validated pack into this Claude/Codex server runtime")
    deploy.add_argument("pack")
    deploy.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    deploy.add_argument("--root", default="~")
    deploy.add_argument("--bin-dir", help="server launcher directory; defaults to <root>/.local/bin")
    deploy.add_argument("--env-file", help="provision the server's private Schift MCP config from this file")
    deploy.add_argument("--hooks", action="store_true", default=True)
    deploy.add_argument("--dry-run", action="store_true")
    deploy.set_defaults(func=cmd_deploy)

    verify_deploy = sub.add_parser("verify-deploy", help="verify an installed Claude/Codex server runtime")
    verify_deploy.add_argument("agent_id")
    verify_deploy.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    verify_deploy.add_argument("--root", default="~")
    verify_deploy.add_argument("--bin-dir")
    verify_deploy.set_defaults(func=cmd_verify_deploy)

    undeploy = sub.add_parser("undeploy", help="remove one deployed pack without removing shared MCP credentials")
    undeploy.add_argument("agent_id")
    undeploy.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    undeploy.add_argument("--root", default="~")
    undeploy.add_argument("--bin-dir")
    undeploy.set_defaults(func=cmd_undeploy)

    ship = sub.add_parser("ship", help="copy a pack to an SSH server and deploy its selected runtimes")
    ship.add_argument("pack")
    ship.add_argument("--target", required=True, help="SSH target, for example deploy@server.example")
    ship.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    ship.add_argument("--remote-root", default="$HOME")
    ship.add_argument("--remote-bin-dir", default="$HOME/.local/bin")
    ship.add_argument("--env-file", help="local env file; used only with --copy-env")
    ship.add_argument("--copy-env", action="store_true", help="send the minimal Schift MCP config over SSH stdin")
    ship.set_defaults(func=cmd_ship)

    catalog = sub.add_parser("catalog", help="show the local connector catalog")
    catalog.set_defaults(func=cmd_catalog)

    studio = sub.add_parser("studio", help="open the local structured APM authoring window")
    studio.add_argument("--host", default="127.0.0.1")
    studio.add_argument("--port", type=int, default=8786)
    studio.add_argument("--output", default="./apm-workspace")
    studio.add_argument("--no-open", action="store_true")
    studio.set_defaults(func=cmd_studio)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"schift-extension: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
