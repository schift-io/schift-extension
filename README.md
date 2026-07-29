# Schift Extension

One local extension for two jobs:

1. Install the Schift Extension into Codex and Claude. It wires the existing
   `@schift-io/mcp` Connector and lifecycle hooks, but does not turn
   MCP itself into a harness.
2. Turn a local `SKILL.md`, `AGENTS.md`, Claude skill, or Codex agent folder
   into a sealed APM pack with an explicit model, connector, MCP, and
   host-capability contract.

The package creates and validates a local artifact first. Registry publication
is a separate explicit action; it never runs during authoring, install, or
server deployment.

## Install Surface

After this package is published to npm:

```bash
npx --yes --package=@schift-io/extension@latest extension install --host both --env-file .env.local
```

During repository development:

```bash
node bin/schift-extension.mjs install --host both --dry-run
node bin/schift-extension.mjs studio
```

`install` safely merges only its marked entries:

- Codex: `~/.codex/config.toml` with an `mcp_servers.schift` entry.
- Claude: `~/.claude.json` with an `mcpServers.schift` entry.
- Hooks: `@schift-io/ai-memory-hooks` summary/metadata capture definitions.
  Hooks never block a host session.

`--env-file` reads `SCHIFT_API_URL` and `SCHIFT_API_KEY`, then writes them only
to `~/.schift/ai-memory/config.json`; the installer never writes API keys into
Codex or Claude configuration files. Remove the extension with
`npx --yes --package=@schift-io/extension@latest extension uninstall`. Add `--purge-local-data` only when
you also want to delete local credentials and queued summaries.

## Authoring Surface

```bash
# Import an existing Claude/Codex skill or agent instruction file.
node bin/schift-extension.mjs import \
  --source ~/.claude/skills/my-skill \
  --name customer-brief \
  --purpose "고객 브리프를 회사 근거로 정리한다" \
  --model openai/gpt-5.4-mini \
  --connector schift-memory --connector schift-write

# Build a deterministic local artifact.
node bin/schift-extension.mjs build ./apm-workspace/customer-brief.agent

# Verify a fresh lightweight virtual environment and the pack boundary.
node bin/schift-extension.mjs verify ./apm-workspace/customer-brief.agent

# Publish the sealed artifact as a private draft owned by the authenticated
# Schift organization and user. Add --make-live only when this version should
# become the runtime default.
node bin/schift-extension.mjs publish ./apm-workspace/customer-brief.agent \
  --env-file .env.local

# Open the local structured authoring window.
node bin/schift-extension.mjs studio
```

The generated folder contains:

```text
customer-brief.agent/
  apm.yml                 shallow, human-reviewable runtime declaration
  pack.json               canonical structured package details
  agent.md                imported agent instruction
  skills/<name>/SKILL.md  imported or scaffolded skill
  runtime/bridge.json     native Codex/Claude/MCP installation contract
  runtime/codex/          Codex plugin payload: manifest, MCP config, skill
  runtime/claude/         Claude plugin payload: manifest, MCP config, skill
  dist/*.apm              deterministic local build output
```

The local UI is intentionally a structured editor, not a YAML editor. YAML
remains an emitted review artifact because existing APM tooling consumes it.

## Server Deployment

`deploy` installs a validated pack into the current server account. It copies
the immutable pack release under `~/.schift-extension/packs`, installs the
skill into both host skill directories, wires the shared Schift MCP and hooks,
and creates a Claude launcher that always loads the pack's instruction and MCP
configuration.

```bash
# Run on the server, after Claude/Codex and Node are installed.
npx --yes --package=@schift-io/extension@latest extension deploy ./customer-brief.agent \
  --host both --env-file .env.local

# Claude uses the deployed instruction and pack-specific MCP config.
~/.local/bin/schift-claude-customer-brief

# Check or remove one pack. This does not remove shared MCP credentials.
npx --yes --package=@schift-io/extension@latest extension verify-deploy customer-brief
npx --yes --package=@schift-io/extension@latest extension undeploy customer-brief
```

From a workstation, send the pack over SSH and invoke the same server-side
deploy lifecycle. The server must already have its private Schift MCP config,
or use `--copy-env` to send only the required Schift variables over SSH stdin.

```bash
npx --yes --package=@schift-io/extension@latest extension ship ./customer-brief.agent \
  --target deploy@server.example --host both
```

APM artifacts never contain Claude credentials, SSH keys, or Schift API keys.

## Registry Publication

`publish` is the only extension command that writes to the APM registry. It
rebuilds the local sealed artifact, sends its content hash to
`POST /v1/apm/registry/packs/upload`, and then reads
`GET /v1/apm/registry/packs` with the same credential. It succeeds only when
the returned APM reference and the owned-pack list agree on `agent_id`,
`owner_org`, and `uploaded_by`.

```bash
# Private draft. This is the default because uploading and making a version
# live are separate operational decisions.
npx --yes --package=@schift-io/extension@latest extension publish \
  ./apm-workspace/customer-brief.agent --env-file .env.local

# Explicitly make a reviewed version live, or publish to an allowlisted org.
npx --yes --package=@schift-io/extension@latest extension publish \
  ./apm-workspace/customer-brief.agent --env-file .env.local \
  --make-live --visibility corporate --allowed-org room821
```

The credential must resolve to a Schift user with an active organization and
either `agents:manage` or organization-admin access. Set
`SCHIFT_APM_PUBLISH_API_KEY` when the publisher key is separate from the
document-ingest `SCHIFT_API_KEY`; the extension stores both only in its private
`~/.schift/ai-memory/config.json`. A document-ingest-only key cannot publish
APMs; the command exits with a specific authorization error instead of claiming
a release succeeded.

## Studio MCP Upload

After a local build, Studio exposes an explicit **Upload manifest to Schift
MCP** action. It queues the generated `pack.json` through
`schift_upload_document` so the APM definition is searchable in Schift. This
is not an APM release. The sealed `.apm` is published only through the
explicit `publish` command, or through the MCP `schift_apm_publish` tool with
the same publisher credential.

The action uses the same private local MCP configuration installed for Codex
and Claude. Provision it from the current repository environment before using
Studio:

```bash
npx --yes --package=@schift-io/extension@latest extension install --host both --env-file .env.local
```

The configured key must have `buckets:manage` for document upload. APM
registry publication additionally requires `agents:manage` or organization-admin access.

## Verification

`verify` creates `.venv-schift-extension` beside the package when needed,
checks generated files, validates the local-BYO capability boundary, and builds
the sealed artifact. It has no third-party Python or model-runtime dependency.

Run the repository checks:

```bash
npm test
npm run smoke
npm run venv:verify
```
