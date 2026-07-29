import { stat } from "node:fs/promises";
import { basename, join, resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const packPath = process.argv[2];
if (!packPath) {
  throw new Error("usage: node mcp-upload.mjs <pack.agent>");
}

const resolvedPack = resolve(packPath);
if (!resolvedPack.endsWith(".agent") || basename(resolvedPack) === ".agent") {
  throw new Error("MCP upload accepts a generated .agent directory only.");
}
if (!(await stat(resolvedPack)).isDirectory() || !(await stat(join(resolvedPack, "pack.json"))).isFile()) {
  throw new Error("MCP upload requires a generated .agent directory with pack.json.");
}
const client = new Client({ name: "schift-extension-studio", version: "1.0.0" });

try {
  await client.connect(
    new StdioClientTransport({
      command: "npx",
      args: ["--yes", "--package=@schift-io/mcp", "schift-mcp"],
      env: {
        ...process.env,
        NODE_OPTIONS: "--dns-result-order=ipv4first",
        SCHIFT_AI_MEMORY_ENABLE_WORKFLOW_TOOLS: "1",
      },
    }),
  );
  const result = await client.callTool({
    name: "schift_apm_publish_local",
    arguments: {
      pack_path: resolvedPack,
      make_live: false,
    },
  });
  const text = result.content.find((item) => item.type === "text")?.text ?? "{}";
  if (result.isError) throw new Error(text);
  const response = JSON.parse(text);
  const published = typeof response.published === "string" ? response.published : "";
  const separator = published.lastIndexOf("@");
  process.stdout.write(`${JSON.stringify({
    ok: true,
    agent_id: typeof response.agent_id === "string"
      ? response.agent_id
      : separator > 0 ? published.slice(0, separator) : null,
    version: typeof response.version === "string"
      ? response.version
      : separator > 0 ? published.slice(separator + 1) : null,
    visibility: typeof response.visibility === "string" ? response.visibility : "private",
    is_live: response.is_live === true || response.live === true,
  })}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({
    ok: false,
    error: error instanceof Error ? error.message : String(error),
  })}\n`);
  process.exitCode = 1;
} finally {
  await client.close();
}
