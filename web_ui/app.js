const AUTH_TOKEN_KEY = 'sidar_access_token';
const AUTH_USER_KEY = 'sidar_user';
let isCurrentUserAdmin = false;

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
  isCurrentUserAdmin = !!(user && (user.role === 'admin' || user.username === 'default_admin'));
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

window.showAdminPanel = async function showAdminPanel() {
  if (!isCurrentUserAdmin) {
    showUiNotice('Admin paneli sadece yetkili kullanıcılar içindir.', 'warn');
    return;
  }
  document.getElementById('task-panel').style.display = 'none';
  document.getElementById('chat-panel').style.display = 'none';
  document.getElementById('admin-panel-container').style.display = 'flex';
  document.querySelectorAll('.nav-tab').forEach((tab) => tab.classList.remove('active'));
  document.getElementById('admin-nav-tab')?.classList.add('active');
  try {
    await loadAdminStats();
  } catch (err) {
    showUiNotice(err.message || 'Admin panel verisi alınamadı', 'warn');
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

    // Global değişkenleri gerçek git bilgisiyle doldur
    currentBranch = branch;
    defaultBranch = data.default_branch || 'main';
    if (repo) currentRepo = repo;

    // Sidebar etiketleri
    const sbl = document.getElementById('sidebar-branch-label');
    if (sbl) sbl.textContent = branch;

    const srl = document.getElementById('sidebar-repo-label');
    if (srl) srl.textContent = repo.split('/').pop() || repo || 'sidar_project';

    // Görev paneli seçici etiketleri
    const branchLabel = document.getElementById('branch-label');
    if (branchLabel) branchLabel.textContent = branch;

    const repoLabel = document.getElementById('repo-label');
    if (repoLabel && repo) repoLabel.textContent = repo;

    // PR Çubuğu: varsayılan dışındaki dallarda göster
    const prBar = document.getElementById('pr-bar');
    if (prBar && branch && branch !== defaultBranch) {
      document.getElementById('pr-base').textContent = defaultBranch;
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
    if (isStreaming) stopStreaming();
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
  if (currentSessionId) {
    await loadSessionHistory(currentSessionId, false);
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
