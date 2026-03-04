const steps = ["Sağlayıcı", "Çalıştırma", "Onay"];
let currentStep = 0;

const state = {
  provider: "ollama",
  level: "full",
  mode: "web",
  log: "INFO",
  model: "qwen2.5-coder:7b",
  host: "127.0.0.1",
  port: 7860,
};

const stepsEl = document.getElementById("steps");
const panelEl = document.getElementById("step-panel");
const resultEl = document.getElementById("result");
const nextBtn = document.getElementById("nextBtn");
const backBtn = document.getElementById("backBtn");

const api = window.pywebview?.api;

async function init() {
  if (api?.get_defaults) {
    const defaults = await api.get_defaults();
    Object.assign(state, defaults);
  }
  render();
}

function render() {
  stepsEl.innerHTML = steps
    .map((s, i) => `<div class="step ${i === currentStep ? "active" : ""}">${i + 1}. ${s}</div>`)
    .join("");

  if (currentStep === 0) {
    panelEl.innerHTML = `
      <div class="grid">
        <label>Sağlayıcı
          <select id="provider"><option>ollama</option><option>gemini</option></select>
        </label>
        <label>Erişim
          <select id="level"><option>restricted</option><option>sandbox</option><option>full</option></select>
        </label>
      </div>
    `;
    bind("provider");
    bind("level");
  } else if (currentStep === 1) {
    panelEl.innerHTML = `
      <div class="grid">
        <label>Mod
          <select id="mode"><option>web</option><option>cli</option></select>
        </label>
        <label>Log
          <select id="log"><option>DEBUG</option><option>INFO</option><option>WARNING</option></select>
        </label>
        <label>Model (CLI)
          <input id="model" />
        </label>
        <label>Web Host
          <input id="host" />
        </label>
        <label>Web Port
          <input id="port" type="number" />
        </label>
      </div>
    `;
    ["mode", "log", "model", "host", "port"].forEach(bind);
  } else {
    panelEl.innerHTML = `
      <p>Seçimlerinizi kontrol edip sistemi başlatabilirsiniz.</p>
      <ul>
        <li>Sağlayıcı: <strong>${state.provider}</strong></li>
        <li>Erişim: <strong>${state.level}</strong></li>
        <li>Mod: <strong>${state.mode}</strong></li>
        <li>Log: <strong>${state.log}</strong></li>
      </ul>
      <button class="btn" id="preview">Komutu Önizle</button>
      <button class="btn" id="start">Sistemi Başlat</button>
    `;
    document.getElementById("preview").onclick = doPreview;
    document.getElementById("start").onclick = doStart;
  }

  nextBtn.style.display = currentStep >= 2 ? "none" : "inline-block";
  backBtn.style.display = currentStep <= 0 ? "none" : "inline-block";
}

function bind(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.value = state[id];
  el.oninput = () => {
    state[id] = id === "port" ? Number(el.value || 0) : el.value;
  };
}

nextBtn.onclick = () => {
  currentStep = Math.min(2, currentStep + 1);
  render();
};

backBtn.onclick = () => {
  currentStep = Math.max(0, currentStep - 1);
  render();
};

async function doPreview() {
  if (!api?.preview_command) {
    resultEl.textContent = "PyWebView API bulunamadı (tarayıcıdan açılmış olabilir).";
    return;
  }
  const data = await api.preview_command(state);
  resultEl.textContent = data.command;
}

async function doStart() {
  if (!api?.start_system) {
    resultEl.textContent = "Başlatma sadece PyWebView içinde kullanılabilir.";
    return;
  }
  const data = await api.start_system(state);
  resultEl.textContent = JSON.stringify(data, null, 2);
}

init();
