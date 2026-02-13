const state = {
  cy: null,
  graph: { people: [], edges: [] },
  selectedNodeId: null,
  selectedEdge: null,
  toastTimer: null,
  selectedImageFile: null,
  selectedImageUrl: null,
};

const graphContainer = document.getElementById("graph");
const edgeDetails = document.getElementById("edge-details");
const edgeSummary = document.getElementById("edge-summary");
const refreshBtn = document.getElementById("refresh-btn");
const addPersonForm = document.getElementById("add-person-form");
const personDetailsEmpty = document.getElementById("person-details-empty");
const personDetailsContent = document.getElementById("person-details-content");
const personSummary = document.getElementById("person-summary");
const deletePersonBtn = document.getElementById("delete-person-btn");
const toast = document.getElementById("toast");
const imageDropzone = document.getElementById("image-dropzone");
const imageFileInput = document.getElementById("image-file-input");
const imagePreviewWrap = document.getElementById("image-preview-wrap");
const imagePreview = document.getElementById("image-preview");
const webSearchToggle = document.getElementById("web-search-toggle");
const extractImageBtn = document.getElementById("extract-image-btn");

function init() {
  suppressDeprecatedConnectionUi();
  addPersonForm.addEventListener("submit", onSubmitPerson);
  deletePersonBtn.addEventListener("click", onDeletePerson);
  refreshBtn.addEventListener("click", () => {
    refreshGraph();
  });
  imageDropzone.addEventListener("click", () => imageFileInput.click());
  imageDropzone.addEventListener("dragover", onImageDragOver);
  imageDropzone.addEventListener("dragleave", onImageDragLeave);
  imageDropzone.addEventListener("drop", onImageDrop);
  imageDropzone.addEventListener("paste", onImagePaste);
  imageDropzone.addEventListener("keydown", onImageDropzoneKeydown);
  imageFileInput.addEventListener("change", onImageFileChosen);
  extractImageBtn.addEventListener("click", onExtractImage);

  if (!window.cytoscape) {
    showToast("Cytoscape failed to load, so graph rendering is unavailable.", true);
    return;
  }
  initGraph();
  refreshGraph();
}

function suppressDeprecatedConnectionUi() {
  const addConnectionForm = document.getElementById("add-connection-form");
  if (addConnectionForm) {
    const section = addConnectionForm.closest("section");
    if (section) {
      section.remove();
    } else {
      addConnectionForm.remove();
    }
  }

  for (const heading of document.querySelectorAll("h2")) {
    if ((heading.textContent || "").trim().toLowerCase() === "add connection") {
      const section = heading.closest("section");
      if (section) {
        section.remove();
      }
    }
  }

  const deleteEdgeBtn = document.getElementById("delete-edge-btn");
  if (deleteEdgeBtn) {
    deleteEdgeBtn.remove();
  }
}

function initGraph() {
  state.cy = window.cytoscape({
    container: graphContainer,
    elements: [],
    style: [
      {
        selector: "node",
        style: {
          label: "data(label)",
          "font-size": 11,
          "font-weight": 700,
          "text-valign": "center",
          "text-halign": "center",
          "background-color": "#0f766e",
          color: "#ffffff",
          "text-outline-color": "#0f766e",
          "text-outline-width": 1,
          width: 48,
          height: 48,
        },
      },
      {
        selector: "node.tier-1",
        style: {
          "background-color": "#ff1744",
          "text-outline-color": "#ff1744",
        },
      },
      {
        selector: "node.tier-2",
        style: {
          "background-color": "#ff9100",
          "text-outline-color": "#ff9100",
        },
      },
      {
        selector: "node.tier-3",
        style: {
          "background-color": "#ffea00",
          color: "#161616",
          "text-outline-color": "#ffea00",
        },
      },
      {
        selector: "node.tier-4",
        style: {
          "background-color": "#00e676",
          color: "#0a1f16",
          "text-outline-color": "#00e676",
        },
      },
      {
        selector: "node:selected",
        style: {
          "border-width": 3,
          "border-color": "#facc15",
        },
      },
      {
        selector: "edge",
        style: {
          width: "mapData(weight, 0, 10, 1.5, 6)",
          "line-color": "#2f6f63",
          opacity: 0.8,
          "curve-style": "bezier",
        },
      },
      {
        selector: "edge.directed",
        style: {
          "target-arrow-shape": "triangle",
          "target-arrow-color": "#2f6f63",
        },
      },
      {
        selector: "edge:selected",
        style: {
          "line-color": "#f59e0b",
          "target-arrow-color": "#f59e0b",
        },
      },
    ],
  });

  state.cy.on("tap", "node", (event) => {
    state.selectedNodeId = event.target.id();
    state.selectedEdge = null;
    edgeDetails.classList.add("hidden");
    renderSelectedPerson();
  });

  state.cy.on("tap", "edge", (event) => {
    state.selectedEdge = event.target.data();
    state.selectedNodeId = null;
    renderSelectedPerson();
    renderSelectedEdge();
  });

  state.cy.on("tap", (event) => {
    if (event.target !== state.cy) {
      return;
    }
    state.selectedNodeId = null;
    state.selectedEdge = null;
    edgeDetails.classList.add("hidden");
    renderSelectedPerson();
  });
}

async function refreshGraph() {
  try {
    const payload = await requestJson("GET", "/api/graph");
    state.graph = payload;
    renderGraph();
    renderSelectedPerson();
    renderSelectedEdge();
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderGraph() {
  if (!state.cy) {
    return;
  }

  const nodeElements = state.graph.people.map((person) => ({
    data: {
      id: person.id,
      label: person.name || person.id,
      tier: person.tier,
    },
    classes: tierClass(person.tier),
  }));

  const edgeElements = state.graph.edges.map((edge) => ({
    data: {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      weight: edge.weight,
      symmetric: edge.symmetric,
      contexts: edge.contexts,
    },
    classes: edge.symmetric ? "" : "directed",
  }));

  state.cy.elements().remove();
  state.cy.add([...nodeElements, ...edgeElements]);

  if (state.cy.elements().length > 0) {
    state.cy
      .layout({
        name: "cose",
        animate: true,
        fit: true,
        padding: 36,
        nodeRepulsion: 8200,
        edgeElasticity: 80,
        idealEdgeLength: 130,
      })
      .run();
  }

  if (state.selectedNodeId) {
    const selectedNode = state.cy.getElementById(state.selectedNodeId);
    if (selectedNode.nonempty()) {
      selectedNode.select();
    } else {
      state.selectedNodeId = null;
    }
  }

  if (state.selectedEdge) {
    const selectedEdge = state.cy.getElementById(state.selectedEdge.id);
    if (selectedEdge.nonempty()) {
      selectedEdge.select();
      state.selectedEdge = selectedEdge.data();
    } else {
      state.selectedEdge = null;
    }
  }
}

function renderSelectedPerson() {
  if (!state.selectedNodeId) {
    personDetailsEmpty.classList.remove("hidden");
    personDetailsContent.classList.add("hidden");
    return;
  }

  const person = state.graph.people.find((candidate) => candidate.id === state.selectedNodeId);
  if (!person) {
    state.selectedNodeId = null;
    personDetailsEmpty.classList.remove("hidden");
    personDetailsContent.classList.add("hidden");
    return;
  }

  personDetailsEmpty.classList.add("hidden");
  personDetailsContent.classList.remove("hidden");
  personSummary.textContent = formatPersonSummary(person);
}

function renderSelectedEdge() {
  if (!state.selectedEdge) {
    edgeDetails.classList.add("hidden");
    return;
  }
  const direction = state.selectedEdge.symmetric ? "<->" : "->";
  edgeSummary.textContent = `${state.selectedEdge.source} ${direction} ${state.selectedEdge.target} | weight: ${state.selectedEdge.weight}`;
  edgeDetails.classList.remove("hidden");
}

async function onSubmitPerson(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = fieldValue(form, "id").trim();
  if (!id) {
    showToast("Person id is required.", true);
    return;
  }

  let payload;
  try {
    payload = buildPersonPayload(form, id);
  } catch (error) {
    showToast(error.message || "Invalid person form values.", true);
    return;
  }

  try {
    await requestJson("POST", "/api/people", payload);
    form.reset();
    state.selectedNodeId = id;
    state.selectedEdge = null;
    showToast(`Saved person ${id}.`);
    await refreshGraph();
  } catch (error) {
    showToast(error.message, true);
  }
}

function buildPersonPayload(form, id) {
  return {
    id,
    name: trimOrEmpty(fieldValue(form, "name")),
    family: trimOrEmpty(fieldValue(form, "family")),
    schools: parseListField(fieldValue(form, "schools")),
    employers: parseListField(fieldValue(form, "employers")),
    location: trimOrEmpty(fieldValue(form, "location")),
    tier: numberOrNull(fieldValue(form, "tier")),
    dependency_weight: numberOrDefault(fieldValue(form, "dependency_weight"), 3),
    decision_nodes: parseJsonArrayField(fieldValue(form, "decision_nodes"), "Decision Nodes"),
    platforms: parseStringMapField(fieldValue(form, "platforms"), "Platforms"),
    societies: parseIntMapField(fieldValue(form, "societies"), "Societies", 1, 5),
    ecosystems: parseListField(fieldValue(form, "ecosystems")),
    close_connections: parseListField(fieldValue(form, "close_connections")),
    family_links: parseJsonArrayField(fieldValue(form, "family_links"), "Family Links"),
    notes: fieldValue(form, "notes").trim(),
  };
}

async function onDeletePerson() {
  if (!state.selectedNodeId) {
    showToast("Select a person first.", true);
    return;
  }
  const personId = state.selectedNodeId;
  const confirmed = window.confirm(`Delete person ${personId} and all connected edges?`);
  if (!confirmed) {
    return;
  }

  try {
    await requestJson("DELETE", `/api/people/${encodeURIComponent(personId)}`);
    state.selectedNodeId = null;
    showToast(`Deleted ${personId}.`);
    await refreshGraph();
  } catch (error) {
    showToast(error.message, true);
  }
}

function onImageDropzoneKeydown(event) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    imageFileInput.click();
  }
}

function onImageDragOver(event) {
  event.preventDefault();
  imageDropzone.classList.add("drag-over");
}

function onImageDragLeave(event) {
  event.preventDefault();
  imageDropzone.classList.remove("drag-over");
}

function onImageDrop(event) {
  event.preventDefault();
  imageDropzone.classList.remove("drag-over");
  const file = event.dataTransfer?.files?.[0];
  setSelectedImageFile(file);
}

function onImagePaste(event) {
  const items = event.clipboardData?.items || [];
  for (const item of items) {
    if (item.type && item.type.startsWith("image/")) {
      const file = item.getAsFile();
      setSelectedImageFile(file);
      event.preventDefault();
      return;
    }
  }
}

function onImageFileChosen(event) {
  const file = event.target?.files?.[0];
  setSelectedImageFile(file);
}

function setSelectedImageFile(file) {
  if (!file) {
    return;
  }
  if (!file.type.startsWith("image/")) {
    showToast("Please choose an image file.", true);
    return;
  }
  state.selectedImageFile = file;
  if (state.selectedImageUrl) {
    URL.revokeObjectURL(state.selectedImageUrl);
  }
  state.selectedImageUrl = URL.createObjectURL(file);
  imagePreview.src = state.selectedImageUrl;
  imagePreviewWrap.classList.remove("hidden");
  showToast("Image ready. Click Extract Fields.");
}

async function onExtractImage() {
  if (!state.selectedImageFile) {
    showToast("Paste or choose an image first.", true);
    return;
  }
  const payload = new FormData();
  payload.append("image", state.selectedImageFile);
  payload.append("web_search", webSearchToggle.checked ? "true" : "false");
  extractImageBtn.disabled = true;
  extractImageBtn.textContent = "Extracting...";
  try {
    const response = await fetch("/api/extract-person", {
      method: "POST",
      body: payload,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(body?.detail || "Extraction failed");
    }
    applyExtractedFields(body?.fields || {});
    if (body?.web_search_fallback && body?.warning) {
      showToast(`${body.warning} Review before saving.`);
    } else {
      showToast("Fields extracted. Review before saving.");
    }
  } catch (error) {
    showToast(error.message || "Extraction failed", true);
  } finally {
    extractImageBtn.disabled = false;
    extractImageBtn.textContent = "Extract Fields";
  }
}

function applyExtractedFields(fields) {
  setFieldIfPresent(addPersonForm, "id", fields.id);
  setFieldIfPresent(addPersonForm, "name", fields.name);
  setFieldIfPresent(addPersonForm, "family", fields.family);
  setFieldIfPresent(addPersonForm, "location", fields.location);
  setFieldIfPresent(addPersonForm, "tier", fields.tier);
  setFieldIfPresent(addPersonForm, "dependency_weight", fields.dependency_weight);
}

function formatPersonSummary(person) {
  const name = person.name ? `${person.name} (${person.id})` : person.id;
  const family = person.family || "n/a";
  const location = person.location || "unknown location";
  const tier = person.tier ?? "n/a";
  const dependency = person.dependency_weight ?? "n/a";
  return `${name} | family: ${family} | location: ${location} | tier: ${tier} | dependency: ${dependency}`;
}

function tierClass(tier) {
  const parsedTier = Number(tier);
  if (!Number.isInteger(parsedTier) || parsedTier < 1 || parsedTier > 4) {
    return "";
  }
  return `tier-${parsedTier}`;
}

function trimOrEmpty(value) {
  return value.trim();
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function numberOrDefault(value, fallback) {
  const parsed = numberOrNull(value);
  return parsed === null ? fallback : parsed;
}

function parseListField(value) {
  return value
    .split(/[,\r\n]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function parseJsonArrayField(value, fieldName) {
  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }
  let parsed;
  try {
    parsed = JSON.parse(trimmed);
  } catch (_error) {
    throw new Error(`${fieldName} must be valid JSON.`);
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`${fieldName} must be a JSON array.`);
  }
  return parsed;
}

function parseStringMapField(value, fieldName) {
  return parseKeyValueMap(value, fieldName, (rawValue) => rawValue);
}

function parseIntMapField(value, fieldName, min, max) {
  return parseKeyValueMap(value, fieldName, (rawValue, key) => {
    const parsed = Number(rawValue);
    if (!Number.isInteger(parsed)) {
      throw new Error(`${fieldName} entry '${key}' must be an integer.`);
    }
    if (parsed < min || parsed > max) {
      throw new Error(`${fieldName} entry '${key}' must be between ${min} and ${max}.`);
    }
    return parsed;
  });
}

function parseKeyValueMap(value, fieldName, parseValue) {
  const result = {};
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  for (const line of lines) {
    const separatorIndex = line.indexOf("=");
    if (separatorIndex <= 0) {
      throw new Error(`${fieldName} entries must use key=value format.`);
    }
    const key = line.slice(0, separatorIndex).trim();
    const rawValue = line.slice(separatorIndex + 1).trim();
    if (!key) {
      throw new Error(`${fieldName} entries must include a key.`);
    }
    if (!rawValue) {
      throw new Error(`${fieldName} entry '${key}' must include a value.`);
    }
    result[key] = parseValue(rawValue, key);
  }
  return result;
}

function fieldValue(form, name) {
  const field = form.elements.namedItem(name);
  if (!field) {
    return "";
  }
  return field.value ?? "";
}

function setFieldIfPresent(form, name, value) {
  if (value === null || value === undefined || value === "") {
    return;
  }
  const field = form.elements.namedItem(name);
  if (!field) {
    return;
  }
  field.value = `${value}`;
}

async function requestJson(method, url, payload = undefined) {
  const headers = {};
  const requestInit = { method, headers };
  if (payload !== undefined) {
    headers["Content-Type"] = "application/json";
    requestInit.body = JSON.stringify(payload);
  }

  const response = await fetch(url, requestInit);
  let body = null;
  try {
    body = await response.json();
  } catch (_error) {
    body = null;
  }

  if (!response.ok) {
    const detail = body?.detail || response.statusText || "Request failed";
    throw new Error(detail);
  }
  return body;
}

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.style.background = isError ? "rgba(143, 31, 21, 0.95)" : "rgba(19, 34, 33, 0.92)";
  toast.classList.remove("hidden");
  if (state.toastTimer) {
    clearTimeout(state.toastTimer);
  }
  state.toastTimer = window.setTimeout(() => {
    toast.classList.add("hidden");
  }, 3200);
}

init();
