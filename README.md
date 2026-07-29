# Schift Extension

One local extension for two jobs:

1. Install the Schift Extension into Codex and Claude. It wires the existing
   `@schift-io/ai-memory-mcp` Connector and lifecycle hooks, but does not turn
   MCP itself into a harness.
2. Turn a local `SKILL.md`, `AGENTS.md`, Claude skill, or Codex agent folder
   into a sealed APM pack with an explicit model, connector, MCP, and
   host-capability contract.

The package intentionally does not publish an APM or mutate a production
registry. It creates and validates a local artifact first.

## Install Surface

After this package is published to npm:

```bash
npx -y @schift-io/extension@latest install --host both --env-file .env.local
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
`npx -y @schift-io/extension@latest uninstall`. Add `--purge-local-data` only when
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
