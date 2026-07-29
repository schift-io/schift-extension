# APM Bridge Studio Design

This local tool is for an operator turning a Claude/Codex workflow into an APM
pack. It follows the repository-level `DESIGN.md` and adds local tokens for the
single job: define one pack and verify it before sharing it with a runtime.

## User Job

```text
User: a Codex or Claude operator with a working agent or skill
Job: make its purpose, model, skills, MCP scope, and host boundary visible
Done when: a validated local .apm artifact and native harness configuration exist
Primary action: APM 만들기
```

## Tokens

- Background: `--ink` and `--paper` create a warm technical workbench, not a
  generic dashboard.
- Accent: `--signal` is reserved for the one primary action and valid states.
- Type: `--font-display` is a Korean-capable editorial sans; `--font-mono` is
  used only for runtime facts and generated paths.
- Spacing: 4px base unit; panels use 16px, 24px, and 32px gaps.
- Shape: panels are 14px; controls are 10px; pills are fully rounded.

## Components

- `PackIntentForm`: purpose, source, output path, and model selection.
- `CapabilityGraph`: a visible left-to-right graph of runtime, model, skills,
  connectors, and MCP access.
- `ValidationResult`: clear pass/fail result with the generated package path.

## States

- Empty: prefilled safe local defaults and one CTA.
- Loading: the CTA changes to `만드는 중` while the request is in flight.
- Success: the artifact path and verification summary remain on the screen.
- Error: the source path or package issue is shown inline without losing input.
