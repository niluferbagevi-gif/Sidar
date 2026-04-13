const AUTH_TOKEN_KEY = 'sidar_access_token';
const AUTH_USER_KEY = 'sidar_user';

// ── Merkezi UI Store — tüm paylaşımlı UI durumu tek kaynakta ──────────────
window.UIStore = window.UIStore || { state: {}, domCache: new Map() };

// Tüm dosyaların ortak kullandığı UI durumu için varsayılan değerler
(function seedUIStore() {
  const defaults = {
    isCurrentUserAdmin:  false,
    isStreaming:         false,
    msgCounter:          0,
    currentRepo:         'niluferbagevi-gif/Sidar',
    currentBranch:       'main',
    defaultBranch:       'main',
    currentSessionId:    null,
    attachedFileContent: null,
    attachedFileName:    null,
    allSessions:         [],
    cachedRepos:         null,
    cachedBranches:      null,
    voiceLive:           {
      lastTranscript: '',
      lastState: 'idle',
      summary: 'Ses websocket tanılama verisi bekleniyor.',
      diagnostics: 'Henüz ek tanı verisi yok.',
      badgeClass: 'idle',
      badgeLabel: 'Bekleniyor',
      log: [],
    },
  };
  const s = window.UIStore.state;
  for (const [k, v] of Object.entries(defaults)) {
    if (!Object.prototype.hasOwnProperty.call(s, k)) s[k] = v;
  }
}());

function getUIState(key, fallback = null) {
  return Object.prototype.hasOwnProperty.call(window.UIStore.state, key)
    ? window.UIStore.state[key]
    : fallback;
}

function setUIState(key, value) {
  window.UIStore.state[key] = value;
  return value;
}

function getCachedEl(id) {
  if (!id) return null;
  if (!window.UIStore.domCache.has(id)) {
    const el = document.getElementById(id);
    if (el) window.UIStore.domCache.set(id, el);
  }
  return window.UIStore.domCache.get(id) || null;
}

function reportUIError(err, fallback = 'Beklenmeyen bir hata oluştu.') {
  const message = (err && err.message) ? err.message : fallback;
  if (typeof showUiNotice === 'function') showUiNotice(message, 'warn');
  return message;
}

function escHtml(value) {
  const text = value == null ? '' : String(value);
  return text.replace(/[&<>"']/g, (char) => (
    { '&': ' ve ', '<': '‹', '>': '›', '"': '＂', "'": '＇' }[char]
  ));
}

window.getUIState = getUIState;
window.setUIState = setUIState;
window.getCachedEl = getCachedEl;
window.reportUIError = reportUIError;
window.escHtml = escHtml;

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || '';
}

function setAuthState(token, user) {
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
  if (user) localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
}

function clearAuthState() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
}

function getAuthUser() {
  try { return JSON.parse(localStorage.getItem(AUTH_USER_KEY) || 'null'); } catch { return null; }
}

async function fetchAPI(url, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  const token = getAuthToken();
  if (token && !opts.headers.Authorization) {
    opts.headers.Authorization = `Bearer ${token}`;
  }
  const resp = await fetch(url, opts);
  if (resp.status === 401) {
    showAuthOverlay('Oturum süresi doldu. Lütfen tekrar giriş yapın.');
  }
  return resp;
}

window.fetchAPI = fetchAPI;

function switchAuthTab(tab) {
  const isLogin = tab === 'login';
  document.getElementById('auth-tab-login')?.classList.toggle('active', isLogin);
  document.getElementById('auth-tab-register')?.classList.toggle('active', !isLogin);
  const lf = document.getElementById('login-form');
  const rf = document.getElementById('register-form');
  if (lf) lf.style.display = isLogin ? '' : 'none';
  if (rf) rf.style.display = isLogin ? 'none' : '';
}

function showAuthOverlay(msg = '') {
  const overlay = document.getElementById('auth-overlay');
  if (overlay) overlay.style.display = 'flex';
  const err = document.getElementById('auth-error');
  if (err) err.textContent = msg || '';
}

function hideAuthOverlay() {
  const overlay = document.getElementById('auth-overlay');
  if (overlay) overlay.style.display = 'none';
}

function renderUserProfile() {
  const user = getAuthUser();
  const box = document.getElementById('user-profile');
  const name = document.getElementById('user-profile-name');
  if (!box || !name) return;
  if (user && user.username) {
    name.textContent = `@${user.username}`;
    box.style.display = 'flex';
  } else {
    box.style.display = 'none';
  }
  setUIState('isCurrentUserAdmin', !!(user && (user.role === 'admin' || user.username === 'default_admin')));
  const adminTab = document.getElementById('admin-nav-tab');
  if (adminTab) adminTab.style.display = isCurrentUserAdmin ? '' : 'none';
}

async function syncCurrentUserFromAPI() {
  if (!getAuthToken()) return null;
  try {
    const res = await fetchAPI('/auth/me');
    if (!res.ok) return null;
    const user = await res.json();
    setAuthState(getAuthToken(), user);
    return user;
  } catch {
    return null;
  }
}

function _fmtNumber(num) {
  return Number(num || 0).toLocaleString('tr-TR');
}

function renderAdminStats(data) {
  document.getElementById('admin-total-users').textContent = _fmtNumber(data.total_users);
  document.getElementById('admin-total-requests').textContent = _fmtNumber(data.total_api_requests);
  document.getElementById('admin-total-tokens').textContent = _fmtNumber(data.total_tokens_used);

  const tbody = document.getElementById('admin-users-tbody');
  const users = data.users || [];
  if (!tbody) return;
  if (!users.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="admin-empty">Kullanıcı bulunamadı.</td></tr>';
    return;
  }

  tbody.innerHTML = users.map((u) => `
    <tr>
      <td>${escHtml(u.username || '-')}</td>
      <td>${escHtml(u.role || 'user')}</td>
      <td>${_fmtNumber(u.daily_token_limit)}</td>
      <td>${_fmtNumber(u.daily_request_limit)}</td>
      <td>${escHtml(u.created_at || '-')}</td>
    </tr>
  `).join('');
}

async function loadAdminStats() {
  const tbody = document.getElementById('admin-users-tbody');
  if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="admin-empty">Veri yükleniyor...</td></tr>';
  const res = await fetchAPI('/admin/stats');
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || data.error || 'Admin istatistikleri alınamadı');
  }
  renderAdminStats(data);
}


function renderBudgetDashboard(data) {
  const totals = data.totals || {};
  document.getElementById('dash-total-calls').textContent = _fmtNumber(totals.calls || 0);
  document.getElementById('dash-total-tokens').textContent = _fmtNumber(totals.total_tokens || 0);
  document.getElementById('dash-total-cost').textContent = `$${Number(totals.cost_usd || 0).toFixed(3)}`;

  const tbody = document.getElementById('dashboard-providers-tbody');
  if (!tbody) return;
  const providers = data.by_provider || {};
  const rows = Object.entries(providers);
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="admin-empty">Henüz sağlayıcı verisi yok.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map(([provider, row]) => {
    const budget = row.budget || {};
    const usage = Number(budget.daily_usage_usd || 0);
    const limit = Number(budget.daily_limit_usd || 0);
    const ratio = limit > 0 ? Math.min(100, Math.round((usage / limit) * 100)) : 0;
    return `
      <tr>
        <td>${escHtml(provider)}</td>
        <td>${_fmtNumber(row.calls || 0)}</td>
        <td>${_fmtNumber(row.total_tokens || 0)}</td>
        <td>$${Number(row.cost_usd || 0).toFixed(3)}</td>
        <td>
          <div class="budget-bar-wrap">
            <div class="budget-bar" style="width:${ratio}%"></div>
          </div>
          <div class="budget-bar-label">$${usage.toFixed(3)} / $${limit.toFixed(2)} (${ratio}%)</div>
        </td>
      </tr>
    `;
  }).join('');
}

async function loadBudgetDashboard() {
  const tbody = document.getElementById('dashboard-providers-tbody');
  if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="admin-empty">Veri yükleniyor...</td></tr>';
  const res = await fetchAPI('/api/budget');
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || data.error || 'Dashboard verisi alınamadı');
  }
  renderBudgetDashboard(data);
}

window.showDashboardPanel = async function showDashboardPanel() {
  document.getElementById('task-panel').style.display = 'none';
  document.getElementById('chat-panel').style.display = 'none';
  document.getElementById('dashboard-panel').style.display = 'flex';
  document.getElementById('admin-panel-container').style.display = 'none';
  if (typeof setActiveTopNav === 'function') {
    setActiveTopNav('dashboard-nav-tab');
  }
  try {
    await loadBudgetDashboard();
  } catch (err) {
    reportUIError(err, 'Dashboard verisi alınamadı');
  }
};

window.showAdminPanel = async function showAdminPanel() {
  if (!getUIState('isCurrentUserAdmin', false)) {
    showUiNotice('Admin paneli sadece yetkili kullanıcılar içindir.', 'warn');
    return;
  }
  document.getElementById('task-panel').style.display = 'none';
  document.getElementById('chat-panel').style.display = 'none';
  document.getElementById('dashboard-panel').style.display = 'none';
  document.getElementById('admin-panel-container').style.display = 'flex';
  if (typeof setActiveTopNav === 'function') {
    setActiveTopNav('admin-nav-tab');
  } else {
    document.querySelectorAll('.nav-tab').forEach((tab) => tab.classList.remove('active'));
    document.getElementById('admin-nav-tab')?.classList.add('active');
  }
  try {
    await loadAdminStats();
    await loadPromptRegistry();
  } catch (err) {
    reportUIError(err, 'Admin panel verisi alınamadı');
  }
};

// ── Prompt Registry ──────────────────────────────────────────────────────────

window.loadPromptRegistry = async function loadPromptRegistry() {
  const tbody = document.getElementById('prompt-registry-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="6" class="admin-empty">Yükleniyor…</td></tr>';
  const role = document.getElementById('prompt-role-filter')?.value || '';
  const url = role ? `/admin/prompts?role_name=${encodeURIComponent(role)}` : '/admin/prompts';
  try {
    const res = await fetchAPI(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Prompt listesi alınamadı');
    const prompts = Array.isArray(data.prompts) ? data.prompts : [];
    document.getElementById('prompt-total-count').textContent = prompts.length;
    const activePrompt = prompts.find(p => p.is_active);
    document.getElementById('prompt-active-role').textContent = activePrompt ? activePrompt.role_name : '—';
    if (!prompts.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="admin-empty">Kayıt bulunamadı.</td></tr>';
      return;
    }
    tbody.innerHTML = prompts.map(p => `
      <tr>
        <td>${p.id}</td>
        <td><code>${p.role_name}</code></td>
        <td>v${p.version}</td>
        <td>${p.is_active ? '<span style="color:#4ade80;font-weight:600;">● Aktif</span>' : '<span style="color:#64748b;">○ Pasif</span>'}</td>
        <td style="font-size:.82rem;">${p.updated_at ? new Date(p.updated_at).toLocaleString('tr-TR') : '—'}</td>
        <td>
          <button class="btn-ghost" style="padding:3px 10px;font-size:.8rem;" onclick="activatePrompt(${p.id})"${p.is_active ? ' disabled' : ''}>Etkinleştir</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="admin-empty">${err.message}</td></tr>`;
  }
};

window.showPromptForm = function showPromptForm() {
  document.getElementById('prompt-form-container').style.display = 'block';
  document.getElementById('prompt-form-text').value = '';
  document.getElementById('prompt-form-activate').checked = true;
};

window.hidePromptForm = function hidePromptForm() {
  document.getElementById('prompt-form-container').style.display = 'none';
};

window.savePrompt = async function savePrompt() {
  const role_name = document.getElementById('prompt-form-role').value;
  const prompt_text = document.getElementById('prompt-form-text').value.trim();
  const activate = document.getElementById('prompt-form-activate').checked;
  if (!prompt_text) { showUiNotice('Prompt metni boş olamaz.', 'warn'); return; }
  try {
    const res = await fetchAPI('/admin/prompts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role_name, prompt_text, activate }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Prompt kaydedilemedi');
    showUiNotice(`Prompt kaydedildi (${role_name} v${data.prompt?.version ?? '?'}).`, 'success');
    hidePromptForm();
    await loadPromptRegistry();
  } catch (err) {
    showUiNotice(err.message, 'error');
  }
};

window.activatePrompt = async function activatePrompt(promptId) {
  try {
    const res = await fetchAPI('/admin/prompts/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt_id: promptId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Etkinleştirme başarısız');
    showUiNotice('Prompt etkinleştirildi.', 'success');
    await loadPromptRegistry();
  } catch (err) {
    showUiNotice(err.message, 'error');
  }
};

async function loginOrRegister(path, username, password) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json();
  if (!res.ok || !data.access_token) {
    throw new Error(data.detail || data.error || 'Giriş başarısız');
  }
  setAuthState(data.access_token, data.user || { username });
  hideAuthOverlay();
  renderUserProfile();
  await loadSessions();
  if (typeof window.connectWebSocket === 'function') {
    window.connectWebSocket();
  }
  if (typeof window.startTodoPoll === 'function') {
    window.startTodoPoll();
  }
}

function logoutUser() {
  clearAuthState();
  window.location.reload();
}
window.logoutUser = logoutUser;
window.switchAuthTab = switchAuthTab;

function bindAuthForms() {
  const loginForm = document.getElementById('login-form');
  const registerForm = document.getElementById('register-form');
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const u = document.getElementById('login-username')?.value?.trim() || '';
      const p = document.getElementById('login-password')?.value || '';
      try {
        await loginOrRegister('/auth/login', u, p);
      } catch (err) {
        showAuthOverlay(err.message);
      }
    });
  }
  if (registerForm) {
    registerForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const u = document.getElementById('register-username')?.value?.trim() || '';
      const p = document.getElementById('register-password')?.value || '';
      try {
        await loginOrRegister('/auth/register', u, p);
      } catch (err) {
        showAuthOverlay(err.message);
      }
    });
  }
}

/* ─── Tema ───────────────────────────────────────────────── */
function toggleTheme() {
  const html = document.documentElement;
  const isDark = html.getAttribute('data-theme') === 'dark';
  const next = isDark ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('sidar-theme', next);
  document.getElementById('theme-btn').textContent = next === 'dark' ? '🌙' : '☀';
}

function applyStoredTheme() {
  const saved = localStorage.getItem('sidar-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = saved === 'dark' ? '🌙' : '☀';
}

async function refreshHealthStrip() {
  try {
    const data = await (await fetchAPI(apiUrl('/status'))).json();
    const ollama = document.getElementById('pill-ollama');
    const gpu = document.getElementById('pill-gpu');
    const vram = document.getElementById('pill-vram');

    if (ollama) {
      const isOn = !!data.ollama_online;
      ollama.className = `health-pill ${isOn ? 'ok' : 'warn'}`;
      ollama.textContent = `🧠 Ollama: ${isOn ? 'Online' : 'Offline'} · ${data.ollama_latency_ms ?? '—'}ms`;
    }

    const devices = data.gpu_devices || [];
    if (gpu) {
      const ok = !!(data.gpu_enabled && devices.length);
      gpu.className = `health-pill ${ok ? 'ok' : 'warn'}`;
      const util = ok && devices[0].utilization_pct !== undefined ? `${devices[0].utilization_pct}%` : 'CPU';
      gpu.textContent = `🎮 GPU: ${util}`;
    }

    if (vram) {
      const d = devices[0] || null;
      if (d && d.total_vram_gb !== undefined) {
        const used = Number(d.allocated_gb || 0).toFixed(1);
        const total = Number(d.total_vram_gb || 0).toFixed(1);
        vram.className = 'health-pill ok';
        vram.textContent = `💾 VRAM: ${used}/${total} GB`;
      } else {
        vram.className = 'health-pill warn';
        vram.textContent = '💾 VRAM: N/A';
      }
    }
  } catch {
    const ollama = document.getElementById('pill-ollama');
    if (ollama) {
      ollama.className = 'health-pill warn';
      ollama.textContent = '🧠 Ollama: erişilemiyor';
    }
  }
}

/* ─── Model bilgisi yükleme ─────────────────────────────── */


async function refreshLlmBudgetStrip() {
  try {
    const data = await (await fetchAPI(apiUrl('/api/budget'))).json();
    const pill = document.getElementById('pill-llm');
    if (!pill) return;

    const totals = data.totals || {};
    const providers = data.by_provider || {};
    const openai = providers.openai || null;
    const anthropic = providers.anthropic || null;
    const activeProvider = openai || anthropic;

    const calls = totals.calls ?? 0;
    const cost = Number(totals.cost_usd ?? 0).toFixed(3);
    const failures = totals.failures ?? 0;

    if (activeProvider && activeProvider.budget) {
      const current = Number(activeProvider.budget.daily_usage_usd ?? 0).toFixed(3);
      const limit = Number(activeProvider.budget.daily_limit_usd ?? 0).toFixed(2);
      const providerName = openai ? 'OpenAI' : 'Anthropic';
      const over = !!(activeProvider.budget.daily_exceeded || activeProvider.budget.total_exceeded);
      pill.className = `health-pill ${over || failures > 0 ? 'warn' : 'ok'}`;
      pill.textContent = `💸 ${providerName}: $${current} / $${limit} · toplam $${cost} · ${calls} çağrı`;
      return;
    }

    pill.className = `health-pill ${failures > 0 ? 'warn' : 'ok'}`;
    pill.textContent = `💸 LLM: $${cost} · ${calls} çağrı`;
  } catch {
    const pill = document.getElementById('pill-llm');
    if (pill) {
      pill.className = 'health-pill warn';
      pill.textContent = '💸 LLM: erişilemiyor';
    }
  }
}

async function loadModelInfo() {
  try {
    const data = await (await fetchAPI(apiUrl('/status'))).json();
    const provider = (data.provider || 'ollama').toLowerCase();
    const model    = data.model || '—';
    const display = provider === 'gemini'
      ? `Gemini · ${model}`
      : provider === 'anthropic'
        ? `Claude · ${model}`
        : model;

    const sidebarLabel = document.getElementById('model-name-label');
    if (sidebarLabel) sidebarLabel.textContent = display;

    const inputLabel = document.getElementById('input-model-label');
    if (inputLabel) inputLabel.textContent = display;

    const modelSelect = document.getElementById('model-select');
    if (modelSelect) modelSelect.value = provider;
  } catch {
    // Sessizce geç
  }
}

function onModelSelectChange() {
  const modelSelect = document.getElementById('model-select');
  if (!modelSelect) return;
  const provider = (modelSelect.value || '').toLowerCase();
  showUiNotice(`Seçilen AI sağlayıcı: ${provider}. Değişikliği uygulamak için servisi --provider ${provider} ile başlatın.`, 'warn');
}

/* ─── Git bilgisi yükleme ───────────────────────────────── */
async function loadGitInfo() {
  try {
    const data = await (await fetchAPI(apiUrl('/git-info'))).json();
    const branch = data.branch || 'main';
    const repo   = data.repo   || '';

    // UIStore'u gerçek git bilgisiyle güncelle
    const localDefaultBranch = data.default_branch || 'main';
    setUIState('currentBranch', branch);
    setUIState('defaultBranch', localDefaultBranch);
    if (repo) setUIState('currentRepo', repo);

    // Sidebar etiketleri
    const sbl = document.getElementById('sidebar-branch-label');
    if (sbl) sbl.textContent = branch;

    const srl = document.getElementById('sidebar-repo-label');
    if (srl) srl.textContent = repo.split('/').pop() || repo || 'Sidar';

    // Görev paneli seçici etiketleri
    const branchLabel = document.getElementById('branch-label');
    if (branchLabel) branchLabel.textContent = branch;

    const repoLabel = document.getElementById('repo-label');
    if (repoLabel && repo) repoLabel.textContent = repo;

    // PR Çubuğu: varsayılan dışındaki dallarda göster
    const prBar = document.getElementById('pr-bar');
    if (prBar && branch && branch !== localDefaultBranch) {
      document.getElementById('pr-base').textContent = localDefaultBranch;
      document.getElementById('pr-head').textContent = branch;
      const viewBtn = document.getElementById('pr-view-btn');
      if (viewBtn && repo) {
        viewBtn.href = `https://github.com/${repo}/compare/${defaultBranch}...${branch}`;
        viewBtn.style.display = 'inline-flex';
      }
      prBar.style.display = 'flex';
    }
  } catch (e) {
    // Git bilgisi alınamazsa sessizce geç
  }
}

/* ─── Modal yardımcıları ────────────────────────────────── */
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

function modalBgClose(e, id) {
  if (e.target === document.getElementById(id)) closeModal(id);
}

/* ─── Durum modalı ──────────────────────────────────────── */
async function openStatus() {
  document.getElementById('status-modal').classList.add('open');
  const grid = document.getElementById('stat-grid');
  grid.innerHTML = '<div class="stat-row"><span class="stat-label">Yükleniyor…</span></div>';
  try {
    const data = await (await fetchAPI(apiUrl('/status'))).json();
    const row = (label, value, cls='') =>
      `<div class="stat-row">
        <span class="stat-label">${label}</span>
        <span class="stat-val ${cls}">${value}</span>
      </div>`;

    // GPU satırlarını oluştur
    let gpuRows = '';
    if (data.gpu_enabled) {
      gpuRows += row('GPU', `✓ ${data.gpu_info || 'Aktif'}`, 'ok');
      if (data.cuda_version && data.cuda_version !== 'N/A') {
        gpuRows += row('CUDA', data.cuda_version);
      }
      if (data.gpu_count > 1) {
        gpuRows += row('GPU Sayısı', `${data.gpu_count} cihaz`);
      }
      (data.gpu_devices || []).forEach(d => {
        const temp  = d.temperature_c  != null ? `  ${d.temperature_c}°C` : '';
        const util  = d.utilization_pct != null ? `  %${d.utilization_pct}` : '';
        gpuRows += row(
          `GPU ${d.id}`,
          `${d.name} · ${d.allocated_gb}/${d.total_vram_gb} GB${temp}${util}`
        );
      });
    } else {
      gpuRows = row('GPU', '✗ CPU modu', 'warn');
    }

    // Güvenlik seviyesi için renk
    const lvlClass = data.access_level === 'restricted' ? 'warn'
                   : data.access_level === 'full'       ? 'ok'
                   : '';
    grid.innerHTML = [
      row('Sürüm',           `v${data.version}`),
      row('AI Sağlayıcı',   `${data.provider} / ${data.model}`),
      row('Erişim Seviyesi', (data.access_level || '').toUpperCase(), lvlClass),
      row('Bellek',          `${data.memory_count} mesaj`),
      row('GitHub',    data.github     ? '✓ Bağlı'         : '✗ Bağlı değil', data.github     ? 'ok' : 'warn'),
      row('Web Arama', data.web_search ? '✓ Aktif'         : '✗ Kurulu değil', data.web_search ? 'ok' : 'warn'),
      row('RAG',       data.rag_status),
      row('Paket Bilgi', data.pkg_status),
      row('Ollama', data.ollama_online ? `Çevrimiçi (${data.ollama_latency_ms ?? '—'} ms)` : 'Çevrimdışı', data.ollama_online ? 'ok' : 'warn'),
      data.enc_status ? row('Bellek Şifreleme', data.enc_status,
        data.enc_status.startsWith('Etkin') ? 'ok' : 'warn') : '',
      gpuRows,
    ].join('');
  } catch (err) {
    grid.innerHTML = `<div class="stat-row"><span class="stat-label">Bağlantı hatası: ${escHtml(err.message)}</span></div>`;
  }
}

/* ─── Bellek temizle ────────────────────────────────────── */
async function clearMemory() {
  if (!confirm('Geçerli konuşma belleği (ekrandaki mesajlar) temizlenecek. Devam edilsin mi?')) return;
  try { await fetchAPI('/clear', { method: 'POST' }); } catch { /* ignore */ }
  document.getElementById('messages').innerHTML = '';
  showTaskPanel();
  loadSessions(); // Menüyü yenile
}

/* ─── Kısayollar modalı ─────────────────────────────────── */
function openShortcuts() {
  document.getElementById('shortcuts-modal').classList.add('open');
}

/* ─── Global klavye kısayolları ─────────────────────────── */
document.addEventListener('keydown', e => {
  // ESC: Modal kapat veya streaming durdur
  if (e.key === 'Escape') {
    ['repo-modal','branch-modal','status-modal','shortcuts-modal','rag-modal'].forEach(id => closeModal(id));
    closeTodoPanel();
    if (getUIState('isStreaming', false)) stopStreaming();
    return;
  }
  // Aktif input/textarea içindeyken kısayolları tetikleme
  const tag = document.activeElement.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;

  // Ctrl+K: Yeni sohbet
  if (e.ctrlKey && e.key === 'k') {
    e.preventDefault();
    createNewSession();
  }
  // Ctrl+L: Belleği temizle
  if (e.ctrlKey && e.key === 'l') {
    e.preventDefault();
    clearMemory();
  }
  // Alt+T: Tema değiştir (Ctrl+T tarayıcıda yeni sekme açar, Alt+T çakışmaz)
  if (e.altKey && e.key === 't') {
    e.preventDefault();
    toggleTheme();
  }
});


window.addEventListener('DOMContentLoaded', async () => {
  const modelSelect = document.getElementById('model-select');
  if (modelSelect) modelSelect.addEventListener('change', onModelSelectChange);

  applyStoredTheme();
  bindAuthForms();
  renderUserProfile();
  if (!getAuthToken()) {
    showAuthOverlay();
    return;
  }
  await syncCurrentUserFromAPI();
  renderUserProfile();
  await loadSessions();
  const _initSessionId = getUIState('currentSessionId', null);
  if (_initSessionId) {
    await loadSessionHistory(_initSessionId, false);
  }
  loadGitInfo();
  loadModelInfo();
  refreshHealthStrip();
  refreshLlmBudgetStrip();
  setInterval(refreshHealthStrip, 8000);
  setInterval(refreshLlmBudgetStrip, 10000);
});

/* ─── Sürükle-Bırak RAG & Sohbet İndirme İşlemleri ───────────────────────── */

// 1. Sürükle ve Bırak (Drag & Drop) Olay Yöneticileri
function _dragOverlayEl() {
  return document.getElementById('drag-overlay');
}

document.addEventListener('dragover', (e) => {
  e.preventDefault();
  const overlay = _dragOverlayEl();
  if (overlay) overlay.classList.add('active');
});

document.addEventListener('dragleave', (e) => {
  const overlay = _dragOverlayEl();
  if (!overlay) return;
  if (e.target === overlay || e.target.id === 'drag-overlay') {
    overlay.classList.remove('active');
  }
});

document.addEventListener('drop', async (e) => {
  e.preventDefault();
  const overlay = _dragOverlayEl();
  if (overlay) overlay.classList.remove('active');

  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    const file = e.dataTransfer.files[0];
    await uploadFileToRAG(file);
  }
});

// Dosyayı sunucuya gönderme fonksiyonu
async function uploadFileToRAG(file) {
  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await fetchAPI(apiUrl('/api/rag/upload'), {
      method: 'POST',
      body: formData
    });

    const result = await response.json();
    if (result.success) {
      alert(`✅ Başarılı: ${result.message}`);
    } else {
      alert(`❌ Hata: ${result.error}`);
    }
  } catch (error) {
    alert(`Bağlantı Hatası: ${error.message}`);
  }
}

// 2. Sohbet İndirme Fonksiyonu
function downloadChat() {
  const chatBox = document.getElementById('messages');
  let mdContent = `# Sidar AI - Sohbet Geçmişi\n\n`;
  const messages = chatBox ? chatBox.querySelectorAll('.message') : [];

  if (messages.length === 0) {
    alert('İndirilecek sohbet bulunmuyor.');
    return;
  }

  messages.forEach(m => {
    const isUser = m.classList.contains('user');
    const role = isUser ? '👤 Siz' : '🤖 Sidar';

    // Markdown'a çevrilmiş ham metni al
    const textElem = m.querySelector('.markdown-body') || m.querySelector('.content');
    const text = textElem ? textElem.innerText : m.textContent;

    mdContent += `### ${role}
${text}

---

`;
  });

  // Dosyayı oluştur ve tarayıcıya indir
  const blob = new Blob([mdContent], { type: 'text/markdown;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);

  const dateStr = new Date().toISOString().slice(0, 10);
  a.download = `sidar_sohbet_${dateStr}.md`;

  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

window.downloadChat = downloadChat;
