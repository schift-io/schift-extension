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
const packList = document.querySelector("#pack-list");
const newPack = document.querySelector("#new-pack");
const MCP_TOOL_LABELS = {
  schift_search: "Search",
  schift_recall: "Recall",
  memory_write: "Write facts",
  document_ingest: "Ingest documents",
};
let selectedPack = null;

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

function selectedMcpTools() {
  return [...form.querySelectorAll('input[name="mcp-tool"]:checked')].map((input) => input.value);
}

function modelLabel(value) {
  return [...model.options].find((option) => option.value === value)?.textContent || value || "host model";
}

function setConnectors(connectors) {
  for (const input of form.querySelectorAll('input[name="connector"]')) {
    input.checked = connectors.includes(input.value);
  }
}

function setMcpTools(tools) {
  for (const input of form.querySelectorAll('input[name="mcp-tool"]')) {
    input.checked = tools.includes(input.value);
  }
}

function syncConnectorsFromMcpTools() {
  const tools = selectedMcpTools();
  const inputs = Object.fromEntries([...form.querySelectorAll('input[name="connector"]')].map((input) => [input.value, input]));
  inputs["schift-memory"].checked = tools.includes("schift_search") || tools.includes("schift_recall");
  inputs["schift-write"].checked = tools.includes("memory_write") || tools.includes("document_ingest");
}

function syncMcpToolsFromConnectors() {
  const connectors = selectedConnectors();
  const tools = new Set(selectedMcpTools());
  for (const tool of ["schift_search", "schift_recall"]) {
    connectors.includes("schift-memory") ? tools.add(tool) : tools.delete(tool);
  }
  for (const tool of ["memory_write", "document_ingest"]) {
    connectors.includes("schift-write") ? tools.add(tool) : tools.delete(tool);
  }
  setMcpTools([...tools]);
}

function resetComposer() {
  selectedPack = null;
  form.elements.name.readOnly = false;
  form.elements.name.value = "my-workflow";
  purpose.value = "Draft a reviewable response from company evidence.";
  model.value = "openai/gpt-5.4-mini";
  source.value = "";
  delete source.dataset.name;
  sourceState.textContent = "NO SOURCE / NEW PACK";
  setConnectors(["schift-memory", "local-model"]);
  setMcpTools(["schift_search", "schift_recall"]);
  form.querySelector('button[type="submit"] span').textContent = "Build APM";
  result.className = "result is-empty";
  result.innerHTML = "<p>READY</p><span>Configure a new APM or select one to adjust.</span>";
  renderGraph();
  renderPackList();
}

function selectPack(pack) {
  selectedPack = pack;
  form.elements.name.value = pack.agent_id;
  form.elements.name.readOnly = true;
  purpose.value = pack.purpose;
  model.value = pack.model || "openai/gpt-5.4-mini";
  source.value = "";
  source.dataset.name = `${pack.agent_id}.agent`;
  sourceState.textContent = `SELECTED / ${pack.agent_id}`;
  setConnectors(Array.isArray(pack.connectors) ? pack.connectors : []);
  setMcpTools(Array.isArray(pack.mcp_tools) ? pack.mcp_tools : []);
  form.querySelector('button[type="submit"] span').textContent = "Save selected APM";
  renderGraph();
  renderPackList();
  renderResult({
    selected: true,
    pack: pack.pack,
    artifact: pack.artifact,
    messages: ["Selected local APM"],
  });
}

let inventory = [];

function renderPackList() {
  if (!inventory.length) {
    packList.innerHTML = '<p class="inventory-empty">No local APMs yet.</p>';
    return;
  }
  packList.innerHTML = inventory.map((pack) => `
    <button class="pack-item${selectedPack?.pack === pack.pack ? " is-selected" : ""}" type="button" data-pack="${escapeHTML(pack.pack)}">
      <b>${escapeHTML(pack.agent_id)}</b>
      <small>${escapeHTML(modelLabel(pack.model))} · ${escapeHTML((pack.connectors || []).join(", ") || "local only")}</small>
    </button>`).join("");
  for (const button of packList.querySelectorAll(".pack-item")) {
    button.addEventListener("click", () => {
      const pack = inventory.find((item) => item.pack === button.dataset.pack);
      if (pack) selectPack(pack);
    });
  }
}

async function loadPacks(selectCurrent = false) {
  const response = await fetch("/api/packs");
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "could not load local APMs");
  inventory = Array.isArray(payload.packs) ? payload.packs : [];
  if (selectCurrent && selectedPack) {
    selectedPack = inventory.find((item) => item.pack === selectedPack.pack) || selectedPack;
  }
  renderPackList();
}

function renderGraph() {
  const connectors = selectedConnectors();
  const mcpTools = selectedMcpTools();
  const modelName = model.options[model.selectedIndex].text;
  const hasMemory = mcpTools.includes("schift_search") || mcpTools.includes("schift_recall");
  const hasWrite = mcpTools.includes("memory_write") || mcpTools.includes("document_ingest");
  const scope = hasWrite ? "read + approved write" : hasMemory ? "read only" : "not connected";
  const hasSource = Boolean(source.dataset.name || source.value);
  const sourceName = source.dataset.name || (source.value ? source.value.split("/").pop() : "New pack");
  document.querySelector("#svg-host").textContent = shorten(sourceName, 20);
  document.querySelector("#svg-source-detail").textContent = source.dataset.name ? "selected local APM" : source.value ? "imported local source" : "no imported skill";
  document.querySelector("#svg-model").textContent = shorten(modelName.replace(/^Codex \/ /, ""), 19);
  document.querySelector("#graph-purpose").textContent = shorten(purpose.value || "Reviewable evidence response", 44);
  connector.textContent = mcpTools.length ? "Schift MCP" : "Local only";
  document.querySelector("#svg-scope").textContent = scope;
  memory.textContent = hasMemory ? "Memory" : "No recall";
  tools.textContent = mcpTools.length ? mcpTools.map((tool) => MCP_TOOL_LABELS[tool]).join(" + ") : "No Schift access";
  memoryNode.classList.toggle("is-disabled", !hasMemory);
  memoryFlow.classList.toggle("is-disabled", !hasMemory);
  writeNode.classList.toggle("is-disabled", !hasWrite);
  writeFlow.classList.toggle("is-disabled", !hasWrite);
  document.querySelector("#svg-write-detail").textContent = hasWrite ? "approval required" : "not connected";
  capabilityGraph.setAttribute("aria-label", `${shorten(purpose.value || "New pack", 60)}. ${modelName}. ${hasSource ? "Local APM selected." : "New APM."} Schift ${scope}.`);
}

function renderResult(payload, isError = false) {
  result.classList.remove("is-empty");
  result.classList.toggle("is-error", isError);
  result.classList.toggle("is-success", !isError);
  const messages = payload.messages || [payload.error];
  const isSelected = payload.selected === true;
  const upload = payload.pack && !isError
    ? `<div class="result-action"><button id="upload-mcp" type="button" data-pack="${escapeHTML(payload.pack)}">Publish private APM</button><span id="upload-state">Registers this sealed pack to your current Schift account. It stays non-live.</span></div>`
    : "";
  const deploy = payload.pack && !isError
    ? `<div class="result-action"><button id="deploy-runtime" type="button" data-pack="${escapeHTML(payload.pack)}">Install in Codex + Claude</button><span id="deploy-state">Adds local skills, Schift MCP, hooks, and the Claude launcher to this computer.</span></div>`
    : "";
  const detail = isError
    ? `<span>${escapeHTML(messages[0] || "Build failed")}</span>`
    : `<span>${isSelected ? "Select an action for this local APM." : `${messages.length} local checks passed`}</span>`;
  const artifact = payload.artifact
    ? `<details class="result-artifact"><summary>Local artifact</summary><code>${escapeHTML(payload.artifact)}</code></details>`
    : "";
  result.innerHTML = `<div class="result-summary"><p>${isError ? "BLOCKED" : isSelected ? "SELECTED" : "VERIFIED"}</p><h2>${isError ? "Build failed" : isSelected ? "Local APM selected" : "Local APM verified"}</h2>${detail}</div>${artifact}${deploy}${upload}`;
  result.querySelector("#deploy-runtime")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const state = result.querySelector("#deploy-state");
    button.disabled = true;
      button.textContent = "Installing locally";
    try {
      const response = await fetch("/api/deploy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pack: button.dataset.pack }),
      });
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || "local install failed");
      state.textContent = `Installed ${body.agent_id}. Run ${body.launcher} to start this Claude agent.`;
      button.textContent = "Runtime installed";
    } catch (error) {
      state.textContent = `Local install failed: ${error.message}`;
      button.disabled = false;
      button.textContent = "Retry local install";
    }
  });
  result.querySelector("#upload-mcp")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const state = result.querySelector("#upload-state");
    button.disabled = true;
    button.textContent = "Publishing through MCP";
    state.textContent = "Starting the local Schift MCP client...";
    try {
      const response = await fetch("/api/upload-mcp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pack: button.dataset.pack }),
      });
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || "MCP APM publication failed");
      const published = [body.publication.agent_id, body.publication.version].filter(Boolean).join("@");
      state.textContent = `Private APM published: ${published || "current pack"}. It is not live.`;
      button.textContent = "Private APM published";
    } catch (error) {
      state.textContent = `MCP APM publication failed: ${error.message}`;
      button.disabled = false;
      button.textContent = "Retry private APM publication";
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

for (const field of [purpose, model, source]) {
  field.addEventListener("input", renderGraph);
  field.addEventListener("change", renderGraph);
}
for (const field of form.querySelectorAll('input[name="connector"]')) {
  field.addEventListener("change", () => {
    syncMcpToolsFromConnectors();
    renderGraph();
  });
}
for (const field of form.querySelectorAll('input[name="mcp-tool"]')) {
  field.addEventListener("change", () => {
    syncConnectorsFromMcpTools();
    renderGraph();
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true;
  submit.querySelector("span").textContent = "Building";
  const data = new FormData(form);
  try {
    const response = await fetch(selectedPack ? "/api/update" : "/api/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...(selectedPack ? { pack: selectedPack.pack } : { name: data.get("name") }),
        purpose: data.get("purpose"),
        model: data.get("model"),
        source: data.get("source"),
        connectors: selectedConnectors(),
        mcp_tools: selectedMcpTools(),
      }),
    });
    const payload = await response.json();
    renderResult(payload, !response.ok || !payload.ok);
    if (response.ok && payload.record) {
      selectedPack = payload.record;
      form.elements.name.readOnly = true;
      form.querySelector('button[type="submit"] span').textContent = "Save selected APM";
      await loadPacks(true);
    }
  } catch (error) {
    renderResult({ error: `Local Studio is unavailable: ${error.message}` }, true);
  } finally {
    submit.disabled = false;
    submit.querySelector("span").textContent = selectedPack ? "Save selected APM" : "Build APM";
  }
});

newPack.addEventListener("click", resetComposer);
loadPacks().catch((error) => {
  packList.innerHTML = `<p class="inventory-empty">Could not load local APMs: ${escapeHTML(error.message)}</p>`;
});
renderGraph();
