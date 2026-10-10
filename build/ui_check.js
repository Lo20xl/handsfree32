const $ = s => document.querySelector(s);
const DEFAULTS = {camera_index:0, sensitivity:0.6, smoothing:0.55, click_threshold:0.28,
                  prediction_ms:45, reanchor:true, drag_px:12, scroll_speed:1.0,
                  scroll_deadzone:0.003, invert_scroll:false, cursor_style:"sky",
                  trail:true, sparkles:true, preview_mode:"wireframe", capture_height:480,
                  start_enabled:false};

/* ---- API: real pywebview bridge, or a mock for plain-browser preview ---- */
const mock = {
  _st:{armed:false, engine_started:true, hand_found:false, fps:0, latency_ms:0, infer_ms:0,
       error:null, cursor_style:"sky", settings:Object.assign({}, DEFAULTS), version:"2.0.0"},
  get_settings(){ return Promise.resolve(Object.assign({}, this._st.settings)); },
  set_setting(k,v){ this._st.settings[k]=v; return Promise.resolve({ok:true, settings:Object.assign({}, this._st.settings)}); },
  reset_settings(){ this._st.settings=Object.assign({}, DEFAULTS); return Promise.resolve({ok:true, settings:Object.assign({}, this._st.settings)}); },
  get_state(){ return Promise.resolve(Object.assign({}, this._st)); },
  get_telemetry(){ return Promise.resolve({ok:true, summary:"(mock diagnostics — run the app for real numbers)"}); },
  set_control(on){ this._st.armed=!!on; return Promise.resolve(Object.assign({}, this._st)); },
  preview(){ return Promise.resolve(null); },
  cameras(){ return Promise.resolve([0,1]); },
  set_camera(i){ this._st.settings.camera_index=i; return Promise.resolve({ok:true, camera_index:i}); },
  refresh_app(){ return Promise.resolve({ok:true}); },
  open_log(){ return Promise.resolve(true); },
};
const api = () => (window.pywebview ? window.pywebview.api : mock);

/* ---- formatting ---- */
const fmt = {
  pct: v => Math.round(v*100) + "%",
  mult: v => v.toFixed(2) + "×",
  thr: v => Math.round(v*100) + "%",
  ms: v => Math.round(v) + " ms",
  px: v => Math.round(v) + " px",
  f3: v => v.toFixed(3),
};
const RANGE_IDS = {sensitivity:"s-sens", smoothing:"s-smooth", click_threshold:"s-thresh",
                   scroll_speed:"s-scroll", prediction_ms:"s-pred", drag_px:"s-drag",
                   scroll_deadzone:"s-dz"};
const METER_MAX = 0.8;   // ratio scale shown on the pinch meter

let lastSettings = null, dragging = false, armed = false;

function setMeterTick(thr){
  const pct = Math.min(100, Math.max(0, (thr / METER_MAX) * 100));
  document.querySelectorAll(".m-tick").forEach(el => { el.style.left = "calc(" + pct + "% - 1px)"; });
}

function applySettings(s){
  lastSettings = s;
  for (const key of Object.keys(RANGE_IDS)){
    const el = $("#" + RANGE_IDS[key]);
    if (el.value !== String(s[key])) el.value = s[key];
    $("#v-" + RANGE_IDS[key].slice(2)).textContent = fmt[el.dataset.fmt](parseFloat(s[key]));
  }
  $("#t-trail").setAttribute("aria-pressed", String(!!s.trail));
  $("#t-spark").setAttribute("aria-pressed", String(s.sparkles !== false));
  $("#t-invert").setAttribute("aria-pressed", String(!!s.invert_scroll));
  $("#t-start").setAttribute("aria-pressed", String(!!s.start_enabled));
  $("#t-anchor").setAttribute("aria-pressed", String(s.reanchor !== false));
  setMeterTick(s.click_threshold || 0.28);
  document.querySelectorAll("#segStyle button").forEach(b =>
    b.classList.toggle("sel", b.dataset.style === s.cursor_style));
  document.querySelectorAll("#segPreview button").forEach(b =>
    b.classList.toggle("sel", b.dataset.pmode === (s.preview_mode || "wireframe")));
  if (s.capture_height) $("#sel-res").value = String(s.capture_height);
  $("#camLabel").textContent = "Camera " + s.camera_index;
}

function updateMeter(l, r, thr){
  const set = (side, val) => {
    const fill = $("#m-fill-" + side), num = $("#m-val-" + side);
    if (val == null){ fill.style.width = "0%"; num.textContent = "—"; return; }
    fill.style.width = Math.min(100, Math.max(0, (val / METER_MAX) * 100)) + "%";
    fill.classList.toggle("hot", val < (thr || 0.28));
    num.textContent = val.toFixed(2);
  };
  set("l", l); set("r", r);
}

function bindRanges(){
  for (const key of Object.keys(RANGE_IDS)){
    const el = $("#" + RANGE_IDS[key]);
    el.addEventListener("input", () => {
      dragging = true;
      $("#v-" + RANGE_IDS[key].slice(2)).textContent = fmt[el.dataset.fmt](parseFloat(el.value));
      if (key === "click_threshold") setMeterTick(parseFloat(el.value));
    });
    el.addEventListener("change", async () => {
      dragging = false;
      await api().set_setting(key, parseFloat(el.value));
    });
  }
}
const bindToggle = (id, key) => $("#" + id).addEventListener("click", async () => {
  const el = $("#" + id);
  const val = el.getAttribute("aria-pressed") !== "true";
  el.setAttribute("aria-pressed", String(val));
  await api().set_setting(key, val);
});

/* ---- status ---- */
function setStatus(tone, text){ const p = $("#statusPill"); p.dataset.tone = tone; $("#statusText").textContent = text; }
function updateState(st){
  const btn = $("#btnControl");
  btn.textContent = st.armed ? "Stop control" : "Start control";
  btn.classList.toggle("on", !!st.armed);
  const hint = $("#hintLine");
  if (st.error){
    setStatus("bad", "Error — see log");
    hint.textContent = st.error; hint.classList.add("error"); hint.classList.remove("warn");
  } else if (st.warning){
    setStatus("warn", "Camera warning");
    hint.textContent = st.warning; hint.classList.add("warn"); hint.classList.remove("error");
  } else {
    hint.textContent = "Move your hand to steer — pinch thumb + middle to left-click. Hold and move to drag.";
    hint.classList.remove("error", "warn");
    if (st.armed && st.hand_found) setStatus("good", "Active");
    else if (st.armed) setStatus("warn", "Searching for hand…");
    else if (st.engine_started) setStatus("", "Paused");
    else setStatus("", "Starting…");
  }
  $("#stFps").textContent = st.fps != null ? st.fps : 0;
  $("#stLat").textContent = st.latency_ms != null ? st.latency_ms : 0;
  $("#stInf").textContent = st.infer_ms != null ? st.infer_ms : 0;
  $("#stHandText").textContent = st.hand_found ? "Hand tracked" : "No hand";
  $("#stHand").dataset.tone = st.hand_found ? "good" : "warn";
  $("#kVers").textContent = st.version || "—";
  $("#kEng").textContent = st.engine_started ? "running" : "starting…";
  $("#fVer").textContent = st.version || "2.0.0";
  if (st.armed && st.hand_found) updateMeter(st.pinch_l, st.pinch_r, (st.settings && st.settings.click_threshold));
  if (st.settings && !dragging) applySettings(st.settings);
}

/* ---- preview loop ---- */
async function previewLoop(){
  const img = $("#preview"), off = $("#previewOff");
  for(;;){
    try {
      const d = await api().preview();
      if (d){ if (img.src !== d) img.src = d; off.style.display = "none"; }
      else {
        off.style.display = "flex";
        off.textContent = (lastSettings && lastSettings.preview_mode === "off")
          ? "Preview off — hand tracking still runs" : "Waiting for camera…";
      }
    } catch(e){ off.style.display = "flex"; off.textContent = "Preview unavailable"; }
    await new Promise(r => setTimeout(r, 110));
  }
}

/* ---- diagnostics dialog ---- */
async function openTelemetry(){
  $("#telOverlay").classList.add("open");
  $("#telText").value = "collecting…";
  try {
    const r = await api().get_telemetry();
    $("#telText").value = (r && r.summary) || "no telemetry";
  } catch(e){ $("#telText").value = "telemetry failed: " + e; }
}

/* ---- init ---- */
async function init(){
  bindRanges();
  $("#btnControl").addEventListener("click", async () => { await api().set_control(!armed); });
  $("#btnReset").addEventListener("click", async () => {
    const r = await api().reset_settings(); if (r && r.settings) applySettings(r.settings);
  });
  $("#btnLog").addEventListener("click", () => api().open_log());
  $("#btnTelemetry").addEventListener("click", openTelemetry);
  $("#btnTelClose").addEventListener("click", () => $("#telOverlay").classList.remove("open"));
  $("#telOverlay").addEventListener("click", (e) => { if (e.target === $("#telOverlay")) $("#telOverlay").classList.remove("open"); });
  $("#btnTelCopy").addEventListener("click", async () => {
    const ta = $("#telText");
    ta.select();
    try { await navigator.clipboard.writeText(ta.value); }
    catch(e){ document.execCommand("copy"); }
    $("#btnTelCopy").textContent = "Copied ✓";
    setTimeout(() => { $("#btnTelCopy").textContent = "Copy to clipboard"; }, 1400);
  });
  $("#segStyle").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll("#segStyle button").forEach(x => x.classList.toggle("sel", x === b));
    await api().set_setting("cursor_style", b.dataset.style);
  });
  $("#segPreview").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll("#segPreview button").forEach(x => x.classList.toggle("sel", x === b));
    await api().set_setting("preview_mode", b.dataset.pmode);
  });
  $("#sel-res").addEventListener("change", async () => {
    const h = parseInt($("#sel-res").value, 10);
    await api().set_setting("capture_height", h);
    if (lastSettings) await api().set_camera(lastSettings.camera_index);  // reopen camera at new resolution
  });
  $("#btnRefresh").addEventListener("click", async () => {
    const b = $("#btnRefresh"); b.disabled = true; b.textContent = "Refreshing…";
    try { await api().refresh_app(); } catch(e){}
    setTimeout(() => { b.disabled = false; b.textContent = "Refresh app"; }, 1500);
  });
  bindToggle("t-trail", "trail");
  bindToggle("t-invert", "invert_scroll");
  bindToggle("t-start", "start_enabled");
  bindToggle("t-spark", "sparkles");
  bindToggle("t-anchor", "reanchor");

  try { applySettings(await api().get_settings()); }
  catch(e){ applySettings(Object.assign({}, DEFAULTS)); }

  (async () => {  // cameras (slow probe — off the critical path)
    try {
      const cams = await api().cameras();
      const sel = $("#sel-cam");
      sel.innerHTML = "";
      for (const c of cams){
        const o = document.createElement("option"); o.value = c;
        o.textContent = c === 0 ? "Default camera (0)" : "Camera " + c;
        sel.appendChild(o);
      }
      sel.value = (lastSettings && lastSettings.camera_index) || 0;
      sel.addEventListener("change", async () => {
        const idx = parseInt(sel.value, 10);
        await api().set_camera(idx);
        $("#camLabel").textContent = "Camera " + idx;
      });
    } catch(e){}
  })();

  previewLoop();
  setInterval(async () => {
    try { const st = await api().get_state(); armed = !!st.armed; updateState(st); }
    catch(e){}
  }, 700);
  updateState({armed:false, engine_started:false, hand_found:false, fps:0, latency_ms:0, infer_ms:0, version:"2.0.0", settings:Object.assign({}, DEFAULTS)});
}

if (window.pywebview) init();
else {
  window.addEventListener("pywebviewready", init, {once:true});
  setTimeout(() => { if (!window.pywebview) init(); }, 1200);  // dev fallback: runs with mock data in a plain browser
}
