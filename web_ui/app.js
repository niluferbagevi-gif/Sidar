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
    const data = await (await fetch(apiUrl('/status'))).json();
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
async function loadModelInfo() {
  try {
    const data = await (await fetch(apiUrl('/status'))).json();
    const provider = (data.provider || 'ollama').toLowerCase();
    const model    = data.model || '—';
    const display  = provider === 'gemini' ? `Gemini · ${model}` : model;

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
    const data = await (await fetch(apiUrl('/git-info'))).json();
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
    const data = await (await fetch(apiUrl('/status'))).json();
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
  try { await fetch('/clear', { method: 'POST' }); } catch { /* ignore */ }
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
  await loadSessions();
  if (currentSessionId) {
    await loadSessionHistory(currentSessionId, false);
  }
  loadGitInfo();
  loadModelInfo();
  refreshHealthStrip();
  setInterval(refreshHealthStrip, 8000);
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
    const response = await fetch(apiUrl('/api/rag/upload'), {
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