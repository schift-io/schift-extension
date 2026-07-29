const form = document.querySelector("#pack-form");
const result = document.querySelector("#result");
const purpose = form.elements.purpose;
const model = form.elements.model;
const source = form.elements.source;
const sourceFile = document.querySelector("#source-file");
const dropzone = document.querySelector("#source-dropzone");
const sourceState = document.querySelector("#source-state");
const capabilityGraph = document.querySelector("#capability-graph");
const connector = document.querySelector("#svg-connector");
const memory = document.querySelector("#svg-memory");
const tools = document.querySelector("#graph-tools");
const memoryNode = document.querySelector("#memory-node");
const memoryFlow = document.querySelector("#memory-flow");
const writeNode = document.querySelector("#write-node");
const writeFlow = document.querySelector("#write-flow");

function shorten(value, limit) {
  const normalized = value.trim().replace(/\s+/g, " ");
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}…` : normalized;
}

function escapeHTML(value) {
  return value.replace(/[&<>"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);
}

function selectedConnectors() {
  return [...form.querySelectorAll('input[name="connector"]:checked')].map((input) => input.value);
}

function renderGraph() {
  const connectors = selectedConnectors();
  const modelName = model.options[model.selectedIndex].text;
  const hasMemory = connectors.includes("schift-memory");
  const hasWrite = connectors.includes("schift-write");
  const scope = hasWrite ? "read + approved write" : hasMemory ? "read only" : "not connected";
  const sourceName = source.dataset.name || (source.value ? source.value.split("/").pop() : "New pack");
  document.querySelector("#svg-host").textContent = shorten(sourceName, 20);
  document.querySelector("#svg-source-detail").textContent = source.value ? "imported local source" : "no imported skill";
  document.querySelector("#svg-model").textContent = shorten(modelName.replace(/^Codex \/ /, ""), 19);
  document.querySelector("#graph-purpose").textContent = shorten(purpose.value || "Reviewable evidence response", 44);
  connector.textContent = hasMemory || hasWrite ? "Schift MCP" : "Local only";
  document.querySelector("#svg-scope").textContent = scope;
  memory.textContent = hasMemory ? "Memory" : "No recall";
  tools.textContent = hasWrite ? "Memory read + approved write" : hasMemory ? "Memory read" : "No Schift access";
  memoryNode.classList.toggle("is-disabled", !hasMemory);
  memoryFlow.classList.toggle("is-disabled", !hasMemory);
  writeNode.classList.toggle("is-disabled", !hasWrite);
  writeFlow.classList.toggle("is-disabled", !hasWrite);
  document.querySelector("#svg-write-detail").textContent = hasWrite ? "approval required" : "not connected";
  capabilityGraph.setAttribute("aria-label", `${shorten(purpose.value || "New pack", 60)}. ${modelName}. Schift ${scope}.`);
}

function renderResult(payload, isError = false) {
  result.classList.remove("is-empty");
  result.classList.toggle("is-error", isError);
  result.classList.toggle("is-success", !isError);
  const messages = payload.messages || [payload.error];
  const upload = payload.pack && !isError
    ? `<button id="upload-mcp" type="button" data-pack="${escapeHTML(payload.pack)}">Upload manifest to Schift MCP</button><span id="upload-state">Keeps the sealed .apm local. Queues pack.json for Schift search.</span>`
    : "";
  const deploy = payload.pack && !isError
    ? `<button id="deploy-runtime" type="button" data-pack="${escapeHTML(payload.pack)}">Install in this server runtime</button><span id="deploy-state">Installs Claude and Codex skills, MCP wiring, hooks, and the Claude launcher.</span>`
    : "";
  const detail = isError
    ? `<span>${escapeHTML(messages[0] || "Build failed")}</span>`
    : `<span>${messages.length} local checks passed</span>`;
  result.innerHTML = `<p>${isError ? "BLOCKED" : "VERIFIED"}</p><h2>${isError ? "Build failed" : "Local APM verified"}</h2>${detail}${payload.artifact ? `<code>${escapeHTML(payload.artifact)}</code>` : ""}${deploy}${upload}`;
  result.querySelector("#deploy-runtime")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const state = result.querySelector("#deploy-state");
    button.disabled = true;
    button.textContent = "Installing runtime";
    try {
      const response = await fetch("/api/deploy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pack: button.dataset.pack }),
      });
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || "runtime deployment failed");
      state.textContent = `Installed ${body.agent_id}. Run ${body.launcher} to start this Claude agent.`;
      button.textContent = "Runtime installed";
    } catch (error) {
      state.textContent = `Runtime install failed: ${error.message}`;
      button.disabled = false;
      button.textContent = "Retry runtime install";
    }
  });
  result.querySelector("#upload-mcp")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const state = result.querySelector("#upload-state");
    button.disabled = true;
    button.textContent = "Queueing through MCP";
    state.textContent = "Starting the local Schift MCP client...";
    try {
      const response = await fetch("/api/upload-mcp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pack: button.dataset.pack }),
      });
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || "MCP upload failed");
      state.textContent = `${body.upload.file_name} queued as ${body.upload.job_id || "an MCP job"}.`;
      button.textContent = "Manifest queued";
    } catch (error) {
      state.textContent = `MCP upload failed: ${error.message}`;
      button.disabled = false;
      button.textContent = "Retry MCP upload";
    }
  });
}

async function stageDroppedFile(file) {
  if (!file) return;
  sourceState.textContent = `IMPORTING / ${file.name}`;
  try {
    const response = await fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: file.name, content: await file.text() }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "could not stage source");
    source.value = payload.source;
    source.dataset.name = file.name;
    sourceState.textContent = `STAGED / ${file.name}`;
    renderGraph();
  } catch (error) {
    sourceState.textContent = `IMPORT FAILED / ${error.message}`;
  }
}

dropzone.addEventListener("click", () => sourceFile.click());
sourceFile.addEventListener("change", () => stageDroppedFile(sourceFile.files[0]));
for (const eventName of ["dragenter", "dragover"]) dropzone.addEventListener(eventName, (event) => { event.preventDefault(); dropzone.classList.add("is-dragging"); });
for (const eventName of ["dragleave", "drop"]) dropzone.addEventListener(eventName, (event) => { event.preventDefault(); dropzone.classList.remove("is-dragging"); });
dropzone.addEventListener("drop", (event) => stageDroppedFile(event.dataTransfer.files[0]));

for (const field of [purpose, model, source, ...form.querySelectorAll('input[name="connector"]')]) {
  field.addEventListener("input", renderGraph);
  field.addEventListener("change", renderGraph);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true;
  submit.querySelector("span").textContent = "Building";
  const data = new FormData(form);
  try {
    const response = await fetch("/api/create", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: data.get("name"), purpose: data.get("purpose"), model: data.get("model"), source: data.get("source"), connectors: selectedConnectors() }) });
    const payload = await response.json();
    renderResult(payload, !response.ok || !payload.ok);
  } catch (error) {
    renderResult({ error: `Local Studio is unavailable: ${error.message}` }, true);
  } finally {
    submit.disabled = false;
    submit.querySelector("span").textContent = "Build APM";
  }
});

renderGraph();
