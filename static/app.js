const state = {
  fixtures: [],
  dmx: null,
  currentValues: {},
  sendTimer: null,
  pollTimer: null,
  selectedSlot: "par",
};

const $ = (id) => document.getElementById(id);

const controls = {
  portSelect: $("portSelect"),
  slotSelect: $("slotSelect"),
  slotEnabledInput: $("slotEnabledInput"),
  slotRanges: $("slotRanges"),
  fixtureSelect: $("fixtureSelect"),
  modeSelect: $("modeSelect"),
  addressInput: $("addressInput"),
  fpsInput: $("fpsInput"),
  rangeLabel: $("rangeLabel"),
  dmxDot: $("dmxDot"),
  dmxStatus: $("dmxStatus"),
  oscDot: $("oscDot"),
  oscStatus: $("oscStatus"),
  colorPreview: $("colorPreview"),
  channelTable: $("channelTable"),
  toast: $("toast"),
  finePanTiltToggleRow: $("finePanTiltToggleRow"),
};

const sliders = [
  ["red", "redInput", "redValue"],
  ["green", "greenInput", "greenValue"],
  ["blue", "blueInput", "blueValue"],
  ["white", "whiteInput", "whiteValue"],
  ["dimmer", "dimmerInput", "dimmerValue"],
  ["strobe", "strobeInput", "strobeValue"],
  ["program", "programInput", "programValue"],
  ["speed", "speedInput", "speedValue"],
  ["pan", "panInput", "panValue"],
  ["tilt", "tiltInput", "tiltValue"],
  ["pan_tilt_speed", "panTiltSpeedInput", "panTiltSpeedValue"],
  ["beat_depth", "beatDepthInput", "beatDepthValue"],
  ["beat_decay_ms", "beatDecayInput", "beatDecayValue"],
];

const swatches = [
  ["Red", [255, 0, 0, 0]],
  ["Green", [0, 255, 0, 0]],
  ["Blue", [0, 0, 255, 0]],
  ["White", [255, 255, 255, 255]],
  ["Amber", [255, 150, 20, 0]],
  ["Cyan", [0, 255, 255, 0]],
  ["Magenta", [255, 0, 255, 0]],
  ["Black", [0, 0, 0, 0]],
];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload;
}

function showToast(message) {
  controls.toast.textContent = message;
  controls.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => controls.toast.classList.remove("visible"), 3200);
}

function getFixtureById(fixtureId) {
  return state.fixtures.find((fixture) => fixture.id === fixtureId);
}

function getMode(fixtureId, modeName) {
  const fixture = getFixtureById(fixtureId);
  return fixture?.modes.find((mode) => mode.name === modeName) || null;
}

function currentSlotId() {
  return controls.slotSelect.value || state.selectedSlot || "par";
}

function currentSlotConfig() {
  return state.dmx?.slots?.[currentSlotId()] || null;
}

function numericValue(id) {
  return Number($(id).value || 0);
}

function setSlider(id, value) {
  const input = $(id);
  input.value = value;
  const output = $(id.replace("Input", "Value"));
  if (output) output.textContent = value;
}

function syncSliderOutputs() {
  sliders.forEach(([, inputId, valueId]) => {
    $(valueId).textContent = $(inputId).value;
  });
  updateColorPreview();
}

function updateColorPreview() {
  const red = numericValue("redInput");
  const green = numericValue("greenInput");
  const blue = numericValue("blueInput");
  const white = numericValue("whiteInput");
  const lift = Math.round(white * 0.42);
  controls.colorPreview.style.backgroundColor = `rgb(${Math.min(255, red + lift)}, ${Math.min(255, green + lift)}, ${Math.min(255, blue + lift)})`;
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined) return "-";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : String(value);
}

function slotPayloadFromControls() {
  return {
    enabled: controls.slotEnabledInput.checked,
    fixture: controls.fixtureSelect.value,
    mode: controls.modeSelect.value,
    address: numericValue("addressInput"),
    color: {
      red: numericValue("redInput"),
      green: numericValue("greenInput"),
      blue: numericValue("blueInput"),
      white: numericValue("whiteInput"),
    },
    dimmer: numericValue("dimmerInput"),
    strobe: numericValue("strobeInput"),
    program: numericValue("programInput"),
    speed: numericValue("speedInput"),
    pan: numericValue("panInput"),
    tilt: numericValue("tiltInput"),
    pan_tilt_speed: numericValue("panTiltSpeedInput"),
    sync_enabled: $("syncEnabledInput").checked,
    beat_pulse_enabled: $("beatPulseEnabledInput").checked,
    osc_strobe_enabled: $("oscStrobeEnabledInput").checked,
    use_fine_pan_tilt: $("useFinePanTiltInput").checked,
    beat_depth: numericValue("beatDepthInput"),
    beat_decay_ms: numericValue("beatDecayInput"),
    color_source: $("colorSourceSelect").value,
  };
}

function populateSlotSelector(dmx) {
  const previousValue = currentSlotId();
  controls.slotSelect.innerHTML = "";
  Object.entries(dmx.slots || {}).forEach(([slotId, slot]) => {
    const option = document.createElement("option");
    option.value = slotId;
    option.textContent = slot.label;
    controls.slotSelect.append(option);
  });
  controls.slotSelect.value = dmx.slots?.[previousValue] ? previousValue : dmx.active_slot;
  state.selectedSlot = controls.slotSelect.value;
}

function setModeOptions(fixtureId, preferredMode) {
  controls.modeSelect.innerHTML = "";
  const fixture = getFixtureById(fixtureId);
  if (!fixture) return;
  fixture.modes.forEach((mode) => {
    const option = document.createElement("option");
    option.value = mode.name;
    option.textContent = `${mode.name} (${mode.footprint}ch)`;
    controls.modeSelect.append(option);
  });
  const match = fixture.modes.find((mode) => mode.name === preferredMode);
  controls.modeSelect.value = match ? preferredMode : fixture.modes[0]?.name || "";
}

function applySlotConfigToControls() {
  const slot = currentSlotConfig();
  if (!slot) return;
  controls.slotEnabledInput.checked = !!slot.enabled;
  controls.fixtureSelect.value = slot.fixture;
  setModeOptions(slot.fixture, slot.mode);
  controls.addressInput.value = slot.address;
  setSlider("redInput", slot.color.red);
  setSlider("greenInput", slot.color.green);
  setSlider("blueInput", slot.color.blue);
  setSlider("whiteInput", slot.color.white);
  setSlider("dimmerInput", slot.dimmer);
  setSlider("strobeInput", slot.strobe);
  setSlider("programInput", slot.program);
  setSlider("speedInput", slot.speed);
  setSlider("panInput", slot.pan);
  setSlider("tiltInput", slot.tilt);
  setSlider("panTiltSpeedInput", slot.pan_tilt_speed);
  setSlider("beatDepthInput", slot.beat_depth);
  setSlider("beatDecayInput", slot.beat_decay_ms);
  $("syncEnabledInput").checked = !!slot.sync_enabled;
  $("beatPulseEnabledInput").checked = !!slot.beat_pulse_enabled;
  $("oscStrobeEnabledInput").checked = !!slot.osc_strobe_enabled;
  $("useFinePanTiltInput").checked = slot.use_fine_pan_tilt !== false;
  $("colorSourceSelect").value = slot.color_source || "manual";
  syncSliderOutputs();
  updateControlVisibility();
  renderChannelTable();
}

function updateControlVisibility() {
  const mode = getMode(controls.fixtureSelect.value, controls.modeSelect.value);
  const types = new Set((mode?.channels || []).map((channel) => channel.type));
  document.querySelectorAll("[data-requires]").forEach((row) => {
    row.classList.toggle("hidden", !types.has(row.dataset.requires));
  });
  controls.finePanTiltToggleRow?.classList.toggle(
    "hidden",
    !(types.has("pan_fine") || types.has("tilt_fine"))
  );
}

function renderSlotRanges(dmx) {
  const ranges = Object.values(dmx.slot_ranges || {}).filter(Boolean);
  const enabledRanges = ranges.filter((range) => range.enabled);
  controls.rangeLabel.textContent = enabledRanges.length
    ? enabledRanges.map((range) => `${range.label} ${range.address}-${range.last_channel}`).join(" · ")
    : "Geen fixture actief";

  controls.slotRanges.innerHTML = "";
  ranges.forEach((range) => {
    const chip = document.createElement("div");
    chip.className = `slot-range${range.enabled ? "" : " off"}`;
    chip.textContent = `${range.label}: ${range.address}-${range.last_channel}`;
    controls.slotRanges.append(chip);
  });
}

function renderChannelTable() {
  const slot = currentSlotConfig();
  const mode = slot ? getMode(slot.fixture, slot.mode) : null;
  const address = slot?.address || 1;
  controls.channelTable.innerHTML = "";
  if (!mode) return;
  mode.channels.forEach((channel) => {
    const absolute = address + channel.offset - 1;
    const row = document.createElement("tr");
    const value = state.currentValues[String(absolute)] ?? 0;
    row.innerHTML = `<td>${absolute}</td><td>${channel.name}</td><td>${value}</td>`;
    controls.channelTable.append(row);
  });
}

function renderSwatches() {
  const holder = $("swatches");
  holder.innerHTML = "";
  swatches.forEach(([name, values]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "swatch";
    button.title = name;
    button.style.backgroundColor = `rgb(${values[0]}, ${values[1]}, ${values[2]})`;
    button.addEventListener("click", () => {
      setSlider("redInput", values[0]);
      setSlider("greenInput", values[1]);
      setSlider("blueInput", values[2]);
      setSlider("whiteInput", values[3]);
      $("colorSourceSelect").value = "manual";
      document.querySelectorAll(".swatch").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      syncSliderOutputs();
      sendUpdate();
    });
    holder.append(button);
  });
}

function renderFixtureOptions() {
  controls.fixtureSelect.innerHTML = "";
  state.fixtures.forEach((fixture) => {
    const option = document.createElement("option");
    option.value = fixture.id;
    option.textContent = `${fixture.manufacturer} ${fixture.model}`;
    controls.fixtureSelect.append(option);
  });
}

async function loadPorts() {
  const payload = await api("/api/ports");
  controls.portSelect.innerHTML = "";
  payload.ports.forEach((port) => {
    const option = document.createElement("option");
    option.value = port.device;
    option.textContent = port.label;
    controls.portSelect.append(option);
  });
  const enttec = payload.ports.find((port) => port.device.includes("usbserial"));
  if (enttec) controls.portSelect.value = enttec.device;
}

function updateStatus(payload) {
  const dmx = payload.dmx;
  const osc = payload.osc;
  const bridge = payload.bridge;

  state.dmx = dmx;
  state.currentValues = dmx.values || {};
  controls.dmxDot.classList.toggle("connected", dmx.connected);
  controls.dmxStatus.textContent = dmx.connected ? "DMX on" : "DMX off";
  if (dmx.port && controls.portSelect.value !== dmx.port) {
    controls.portSelect.value = dmx.port;
  }

  populateSlotSelector(dmx);
  renderSlotRanges(dmx);
  applySlotConfigToControls();

  controls.oscDot.classList.toggle("connected", osc.running && !osc.stale);
  controls.oscDot.classList.toggle("warn", osc.running && osc.stale);
  controls.oscStatus.textContent = osc.running && !osc.stale ? "OSC live" : "OSC idle";
  $("bpmValue").textContent = formatNumber(osc.bpm, 1);
  $("beatValue").textContent = formatNumber(osc.beat, 2);
  $("phraseValue").textContent = osc.phrase_current || "-";
  $("moodValue").textContent = formatNumber(osc.mood, 0);
  $("bankValue").textContent = osc.color_bank ?? "-";
  $("waveformValue").textContent = formatNumber(osc.waveform_energy, 2);
  $("strobeOscValue").textContent = osc.strobe_active ? "on" : "off";
  $("lastMessage").textContent = osc.last_message
    ? `${osc.last_message.address} = ${osc.last_message.text ?? formatNumber(osc.last_message.numeric, 2)}`
    : "-";

  $("startBridgeBtn").classList.toggle("primary", !bridge.running);
  $("stopBridgeBtn").classList.toggle("danger", bridge.running);

  if (dmx.error) showToast(dmx.error);
  if (osc.error) showToast(osc.error);
  if (dmx.conflicts?.length) {
    showToast(`Kanaalconflict op ${dmx.conflicts.map((item) => item.channel).join(", ")}`);
  }
}

async function connect() {
  if (!controls.portSelect.value) {
    showToast("Geen DMX-poort gevonden");
    return;
  }
  const payload = await api("/api/dmx/connect", {
    method: "POST",
    body: JSON.stringify({ port: controls.portSelect.value, fps: numericValue("fpsInput") }),
  });
  updateStatus(payload);
}

async function disconnect() {
  updateStatus(await api("/api/dmx/disconnect", { method: "POST", body: "{}" }));
}

async function blackout() {
  updateStatus(await api("/api/dmx/blackout", { method: "POST", body: "{}" }));
}

async function startBridge() {
  updateStatus(
    await api("/api/bridge/start", {
      method: "POST",
      body: JSON.stringify({ destination: "127.0.0.1:4460" }),
    })
  );
}

async function stopBridge() {
  updateStatus(await api("/api/bridge/stop", { method: "POST", body: "{}" }));
}

async function sendActiveSlotSelection() {
  try {
    updateStatus(
      await api("/api/dmx/update", {
        method: "POST",
        body: JSON.stringify({ active_slot: currentSlotId() }),
      })
    );
  } catch (error) {
    showToast(error.message);
  }
}

function queueUpdate() {
  clearTimeout(state.sendTimer);
  state.sendTimer = setTimeout(sendUpdate, 45);
}

async function sendUpdate() {
  clearTimeout(state.sendTimer);
  try {
    updateStatus(
      await api("/api/dmx/update", {
        method: "POST",
        body: JSON.stringify({
          active_slot: currentSlotId(),
          slot_id: currentSlotId(),
          slot: slotPayloadFromControls(),
        }),
      })
    );
  } catch (error) {
    showToast(error.message);
  }
}

function bindEvents() {
  $("refreshPortsBtn").addEventListener("click", () => loadPorts().catch((error) => showToast(error.message)));
  $("connectBtn").addEventListener("click", () => connect().catch((error) => showToast(error.message)));
  $("disconnectBtn").addEventListener("click", () => disconnect().catch((error) => showToast(error.message)));
  $("blackoutBtn").addEventListener("click", () => blackout().catch((error) => showToast(error.message)));
  $("startBridgeBtn").addEventListener("click", () => startBridge().catch((error) => showToast(error.message)));
  $("stopBridgeBtn").addEventListener("click", () => stopBridge().catch((error) => showToast(error.message)));

  controls.slotSelect.addEventListener("change", () => {
    state.selectedSlot = controls.slotSelect.value;
    applySlotConfigToControls();
    sendActiveSlotSelection();
  });
  controls.slotEnabledInput.addEventListener("change", sendUpdate);
  controls.fixtureSelect.addEventListener("change", () => {
    setModeOptions(controls.fixtureSelect.value, controls.modeSelect.value);
    updateControlVisibility();
    sendUpdate();
  });
  controls.modeSelect.addEventListener("change", () => {
    updateControlVisibility();
    sendUpdate();
  });
  controls.addressInput.addEventListener("change", sendUpdate);
  controls.fpsInput.addEventListener("change", sendUpdate);
  $("syncEnabledInput").addEventListener("change", sendUpdate);
  $("beatPulseEnabledInput").addEventListener("change", sendUpdate);
  $("oscStrobeEnabledInput").addEventListener("change", sendUpdate);
  $("useFinePanTiltInput").addEventListener("change", sendUpdate);
  $("colorSourceSelect").addEventListener("change", sendUpdate);

  sliders.forEach(([, inputId, valueId]) => {
    $(inputId).addEventListener("input", () => {
      $(valueId).textContent = $(inputId).value;
      updateColorPreview();
      queueUpdate();
    });
  });
}

async function pollState() {
  try {
    updateStatus(await api("/api/state"));
  } catch (error) {
    showToast(error.message);
  }
}

async function init() {
  bindEvents();
  renderSwatches();
  state.fixtures = (await api("/api/fixtures")).fixtures;
  renderFixtureOptions();
  await loadPorts();
  updateStatus(await api("/api/state"));
  syncSliderOutputs();
  state.pollTimer = setInterval(pollState, 750);
}

init().catch((error) => showToast(error.message));
