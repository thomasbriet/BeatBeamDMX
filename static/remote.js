const remoteState = {
  app: null,
  pollTimer: null,
  busy: false,
};
const authToken = new URLSearchParams(window.location.search).get("token");

const $ = (id) => document.getElementById(id);

const colorOptions = [
  { value: "none", title: "Auto", swatch: "linear-gradient(90deg, #39404b, #242a34)" },
  { value: "red", title: "Red", swatch: "#ff392e" },
  { value: "yellow", title: "Yellow", swatch: "#ffd61b" },
  { value: "green", title: "Green", swatch: "#2fe85e" },
  { value: "lime", title: "Lime", swatch: "#8cff1f" },
  { value: "purple", title: "Purple", swatch: "#9d3dff" },
  { value: "pink", title: "Pink", swatch: "#ff2f9f" },
  { value: "cyan", title: "Cyan", swatch: "#16e1e9" },
  { value: "orange", title: "Orange", swatch: "#ff8125" },
  { value: "blue", title: "Blue", swatch: "#2f6dff" },
  { value: "white", title: "White", swatch: "#f5f7fa" },
  { value: "rainbow", title: "Rainbow", swatch: "linear-gradient(90deg, #ff453a, #ffcf33, #34c759, #32ade6, #bf5af2)" },
];

const styleOptions = [
  { value: "adaptive", title: "Adaptive" },
  { value: "club", title: "Club" },
  { value: "cinematic", title: "Cinematic" },
  { value: "warm", title: "Warm" },
  { value: "festival", title: "Festival" },
  { value: "minimal", title: "Minimal" },
];

const effectOptions = [
  { key: "override_manual_strobe", title: "Manual Strobe" },
  { key: "override_audience_sweep", title: "Audience Sweep" },
  { key: "override_all_on", title: "All On" },
  { key: "override_par_chase", title: "PAR Chase" },
  { key: "override_par_snake", title: "PAR Snake" },
];

const cueOptions = [
  { value: "audience_riser", title: "Audience Rise" },
  { value: "white_hit", title: "White Hit" },
  { value: "color_burst", title: "Color Burst" },
  { value: "snap_fan", title: "Snap Fan" },
  { value: "mirror_bounce", title: "Mirror Bounce" },
  { value: "par_chase_burst", title: "PAR Chase" },
];

async function api(path, options = {}) {
  const target = new URL(path, window.location.origin);
  if (authToken) {
    target.searchParams.set("token", authToken);
  }
  const response = await fetch(target, {
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
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("visible"), 1800);
}

function activeSlot() {
  return remoteState.app?.dmx?.active_slot || "head";
}

function currentAutoShowPatch(patch) {
  return {
    active_slot: activeSlot(),
    auto_show: patch,
  };
}

async function postUpdate(payload) {
  if (remoteState.busy) return;
  remoteState.busy = true;
  try {
    const app = await api("/api/dmx/update", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    applyState(app);
  } finally {
    remoteState.busy = false;
  }
}

async function triggerBlackout() {
  if (remoteState.busy) return;
  remoteState.busy = true;
  try {
    const app = await api("/api/dmx/blackout", {
      method: "POST",
      body: JSON.stringify({}),
    });
    applyState(app);
  } finally {
    remoteState.busy = false;
  }
}

async function triggerCue(cueID) {
  if (remoteState.busy) return;
  remoteState.busy = true;
  try {
    const app = await api("/api/dmx/trigger-cue", {
      method: "POST",
      body: JSON.stringify({ cue_id: cueID }),
    });
    applyState(app);
  } finally {
    remoteState.busy = false;
  }
}

function numericText(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function setStatusDot(id, status) {
  const el = $(id);
  el.classList.remove("connected", "warn");
  if (status === "connected") el.classList.add("connected");
  if (status === "warn") el.classList.add("warn");
}

function renderColorButtons(autoShow) {
  const current = autoShow.override_color || "none";
  $("colorButtons").innerHTML = colorOptions.map((option) => `
    <button
      type="button"
      class="color-button ${current === option.value ? "selected" : ""}"
      data-color="${option.value}"
    >
      <span class="color-swatch" style="background:${option.swatch};"></span>
      <span>${option.title}</span>
    </button>
  `).join("");

  document.querySelectorAll("[data-color]").forEach((button) => {
    button.addEventListener("click", async () => {
      const value = button.getAttribute("data-color");
      await postUpdate(currentAutoShowPatch({ override_color: value }));
      showToast(`Color ${button.textContent.trim()}`);
    });
  });
}

function renderStyleButtons(autoShow) {
  const current = autoShow.style || "adaptive";
  const enabled = !!autoShow.enabled;
  $("styleButtons").innerHTML = styleOptions.map((option) => `
    <button
      type="button"
      class="${current === option.value ? "selected" : ""}"
      data-style="${option.value}"
    >
      <span>${option.title}</span>
      <small class="subtle">${enabled && current === option.value ? "active" : "set"}</small>
    </button>
  `).join("");

  document.querySelectorAll("[data-style]").forEach((button) => {
    button.addEventListener("click", async () => {
      const value = button.getAttribute("data-style");
      await postUpdate(currentAutoShowPatch({ style: value }));
      showToast(`Style ${value}`);
    });
  });
}

function renderEffectButtons(autoShow) {
  const container = $("effectButtons");
  container.innerHTML = effectOptions.map((option) => {
    const enabled = !!autoShow[option.key];
    return `
      <button
        type="button"
        class="${enabled ? "toggled" : ""}"
        data-effect="${option.key}"
      >
        <span>${option.title}</span>
        <small class="subtle">${enabled ? "On" : "Off"}</small>
      </button>
    `;
  }).join("");

  document.querySelectorAll("[data-effect]").forEach((button) => {
    button.addEventListener("click", async () => {
      const key = button.getAttribute("data-effect");
      const next = !autoShow[key];
      const patch = {};
      patch[key] = next;
      await postUpdate(currentAutoShowPatch(patch));
      showToast(`${button.querySelector("span").textContent} ${next ? "on" : "off"}`);
    });
  });
}

function renderCueButtons(autoShow) {
  const container = $("cueButtons");
  const activeCue = autoShow.one_shot_cue || "none";
  container.innerHTML = cueOptions.map((cue) => `
    <button
      type="button"
      class="${activeCue === cue.value ? "toggled" : ""}"
      data-cue="${cue.value}"
    >
      <span>${cue.title}</span>
      <small class="subtle">${activeCue === cue.value ? `${Math.round((autoShow.one_shot_progress || 0) * 100)}%` : "Fire"}</small>
    </button>
  `).join("");

  document.querySelectorAll("[data-cue]").forEach((button) => {
    button.addEventListener("click", async () => {
      const cueID = button.getAttribute("data-cue");
      await triggerCue(cueID);
      showToast(button.querySelector("span").textContent);
    });
  });
}

function applyState(app) {
  remoteState.app = app;
  const dmx = app.dmx;
  const osc = app.osc;
  const autoShow = dmx.auto_show;

  $("trackMeta").textContent = [app.osc.track_title || "(geen track)", app.osc.track_artist || "onbekend"].join(" • ");
  $("cueBadge").textContent = autoShow.cue_label || "Auto Show uit";
  $("bpmValue").textContent = numericText(osc.bpm, 2);
  $("beatValue").textContent = osc.beat_display ? Math.floor(osc.beat_display) : (osc.beat ? Math.floor(osc.beat) : "-");
  $("phraseValue").textContent = osc.phrase_current || "-";
  $("nextValue").textContent = osc.phrase_next || "-";

  $("dmxStatus").textContent = dmx.connected ? "DMX live" : "DMX off";
  setStatusDot("dmxDot", dmx.connected ? "connected" : "warn");
  $("oscStatus").textContent = osc.stale ? "OSC stale" : "OSC live";
  setStatusDot("oscDot", osc.stale ? "warn" : "connected");

  $("autoShowToggle").checked = !!autoShow.enabled;
  $("autoShowDetail").textContent =
    `${autoShow.style_label} • ${autoShow.theme_label || autoShow.theme_name || "theme"} • ${autoShow.motion_label || autoShow.motion_name || "motion"} • ${autoShow.dimmer_fx_label || autoShow.dimmer_fx_name || "dimmer"}`;

  const overrideParts = [
    autoShow.override_color_label && autoShow.override_color !== "none" ? autoShow.override_color_label : null,
    autoShow.override_manual_strobe ? "strobe" : null,
    autoShow.override_audience_sweep ? "audience sweep" : null,
    autoShow.override_all_on ? "all on" : null,
    autoShow.override_par_chase ? "par chase" : null,
    autoShow.override_par_snake ? "par snake" : null,
  ].filter(Boolean);
  $("overrideSummary").textContent = overrideParts.length ? overrideParts.join(" • ") : "Geen overrides";
  $("cueSummary").textContent = autoShow.one_shot_active
    ? `${autoShow.one_shot_label || autoShow.one_shot_cue || "Cue"} • ${Math.round((autoShow.one_shot_progress || 0) * 100)}%`
    : "Geen cue actief";

  renderStyleButtons(autoShow);
  renderColorButtons(autoShow);
  renderEffectButtons(autoShow);
  renderCueButtons(autoShow);

  $("blackoutBtn").classList.toggle("toggled", !!dmx.blackout_active);
  $("releaseBlackoutBtn").disabled = !dmx.blackout_active;
}

async function refreshState() {
  const app = await api("/api/state");
  applyState(app);
}

function wireStaticControls() {
  $("autoShowToggle").addEventListener("change", async (event) => {
    await postUpdate(currentAutoShowPatch({ enabled: event.target.checked }));
    showToast(event.target.checked ? "Auto Show on" : "Auto Show off");
  });

  $("clearOverridesBtn").addEventListener("click", async () => {
    await postUpdate(currentAutoShowPatch({
      override_color: "none",
      override_manual_strobe: false,
      override_audience_sweep: false,
      override_all_on: false,
      override_par_chase: false,
      override_par_snake: false,
    }));
    showToast("Overrides cleared");
  });

  $("blackoutBtn").addEventListener("click", async () => {
    await triggerBlackout();
    showToast("Blackout");
  });

  $("releaseBlackoutBtn").addEventListener("click", async () => {
    await postUpdate({ active_slot: activeSlot(), blackout_active: false });
    showToast("Blackout released");
  });
}

async function boot() {
  wireStaticControls();
  try {
    await refreshState();
  } catch (error) {
    showToast(error.message);
  }
  remoteState.pollTimer = setInterval(async () => {
    try {
      await refreshState();
    } catch (_) {
      // keep last known state on transient network issues
    }
  }, 250);
}

boot();
