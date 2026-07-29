const form = document.querySelector("#pack-form");
const result = document.querySelector("#result");
const purpose = form.elements.purpose;
const model = form.elements.model;
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

function selectedConnectors() {
  return [...form.querySelectorAll('input[name="connector"]:checked')].map(
    (input) => input.value,
  );
}

function renderGraph() {
  const connectors = selectedConnectors();
  const modelName = model.options[model.selectedIndex].text;
  const graphPurpose = purpose.value || "업무 목적";
  document.querySelector("#graph-purpose").textContent = shorten(graphPurpose, 44);
  document.querySelector("#svg-model").textContent = shorten(modelName.replace(/^Codex \/ /, ""), 19);
  const hasMemory = connectors.includes("schift-memory");
  const hasWrite = connectors.includes("schift-write");
  const scope = hasWrite ? "read + approved write" : hasMemory ? "read only" : "not connected";
  connector.textContent = hasMemory || hasWrite ? "Schift MCP" : "Local only";
  document.querySelector("#svg-scope").textContent = scope;
  memory.textContent = hasMemory ? "Memory" : "No recall";
  tools.textContent = hasWrite ? "Memory read + approved write" : hasMemory ? "Memory read" : "No Schift data access";
  memoryNode.classList.toggle("is-disabled", !hasMemory);
  memoryFlow.classList.toggle("is-disabled", !hasMemory);
  writeNode.classList.toggle("is-disabled", !hasWrite);
  writeFlow.classList.toggle("is-disabled", !hasWrite);
  document.querySelector("#svg-write-detail").textContent = hasWrite ? "approval required" : "not connected";
  capabilityGraph.setAttribute("aria-label", `${shorten(graphPurpose, 60)}. ${modelName} 실행. Schift ${scope}.`);
}

function renderResult(payload, isError = false) {
  result.classList.remove("is-empty");
  result.classList.toggle("is-error", isError);
  result.classList.toggle("is-success", !isError);
  const messages = payload.messages || [payload.error];
  result.innerHTML = `
    <p class="kicker">03 / VERIFY</p>
    <h2>${isError ? "생성하지 못했습니다." : "로컬 APM을 검증했습니다."}</h2>
    <p>${isError ? "입력은 유지됩니다. 경로와 필수 값을 확인한 뒤 다시 시도하세요." : "봉인된 로컬 아티팩트가 준비되었습니다."}</p>
    <ul>${messages.map((message) => `<li>${message}</li>`).join("")}</ul>
    ${payload.pack ? `<code>${payload.pack}</code>` : ""}
    ${payload.artifact ? `<code>${payload.artifact}</code>` : ""}
  `;
}

for (const field of [purpose, model, ...form.querySelectorAll('input[name="connector"]')]) {
  field.addEventListener("input", renderGraph);
  field.addEventListener("change", renderGraph);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = form.querySelector("button");
  submit.disabled = true;
  submit.textContent = "만드는 중";
  const data = new FormData(form);
  const payload = {
    name: data.get("name"),
    purpose: data.get("purpose"),
    model: data.get("model"),
    source: data.get("source"),
    connectors: selectedConnectors(),
  };
  try {
    const response = await fetch("/api/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    renderResult(body, !response.ok || !body.ok);
  } catch (error) {
    renderResult({ error: `로컬 작성기와 통신하지 못했습니다: ${error.message}` }, true);
  } finally {
    submit.disabled = false;
    submit.textContent = "APM 만들기";
  }
});

renderGraph();
