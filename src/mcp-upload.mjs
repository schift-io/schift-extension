import { readFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const packPath = process.argv[2];
if (!packPath) {
  throw new Error("usage: node mcp-upload.mjs <pack.json>");
}

const resolvedPack = resolve(packPath);
if (basename(resolvedPack) !== "pack.json") {
  throw new Error("MCP upload accepts a generated pack.json manifest only.");
}

const content = await readFile(resolvedPack, "utf8");
const manifest = JSON.parse(content);
const agentId = typeof manifest.agent_id === "string" ? manifest.agent_id : "apm-pack";
const client = new Client({ name: "schift-extension-studio", version: "1.0.0" });

try {
  await client.connect(
    new StdioClientTransport({
      command: "npx",
      args: ["-y", "@schift-io/ai-memory-mcp@latest"],
      env: { ...process.env, SCHIFT_AI_MEMORY_ENABLE_WORKFLOW_TOOLS: "1" },
    }),
  );
  const result = await client.callTool({
    name: "schift_upload_document",
    arguments: {
      filename: `${agentId}.apm.json`,
      text: content,
      content_type: "application/json",
      metadata: {
        source: "schift-extension-studio",
        artifact_kind: "apm_manifest",
        apm_agent_id: agentId,
      },
    },
  });
  const text = result.content.find((item) => item.type === "text")?.text ?? "{}";
  const response = JSON.parse(text);
  const job = Array.isArray(response.jobs) ? response.jobs[0] : undefined;
  process.stdout.write(`${JSON.stringify({
    ok: true,
    job_id: typeof job?.job_id === "string" ? job.job_id : null,
    file_name: typeof job?.file_name === "string" ? job.file_name : `${agentId}.apm.json`,
    status: typeof job?.status === "string" ? job.status : "queued",
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
