
marked.setOptions({ breaks: true, gfm: true });

/* ─── Değişkenler ───────────────────────────────────────── */
let isStreaming    = false;
let msgCounter     = 0;
let currentRepo    = 'niluferbagevi-gif/sidar_project';
let currentBranch  = 'main';
let defaultBranch  = 'main';   // Repo'nun varsayılan hedef branch'i (PR base)
let currentSessionId = null;
let attachedFileContent = null;
let attachedFileName    = null;
let allSessions = [];
let _cachedRepos = null;
const API_URL = window.location.origin;
let chatSocket = null;
let wsReconnectTimer = null;
let currentStream = null;

function apiUrl(path) {
  return `${API_URL}${path}`;
}

function showUiNotice(message, level = 'warn') {
  const box = document.getElementById('ui-notice');
  if (!box) return;
  box.className = `ui-notice ${level}`;
  box.textContent = message;
  box.style.display = 'block';
  clearTimeout(showUiNotice._timer);
  showUiNotice._timer = setTimeout(() => {
    box.style.display = 'none';
  }, 4200);
}

/* ─── Görev başlat ──────────────────────────────────────── */
function startTask() {
  const text = document.getElementById('task-input').value.trim();
  if (!text) return;
  document.getElementById('task-input').value = '';
  showChatPanel();
  sendText(text);
}

function quickTask(text) {
  document.getElementById('task-input').value = text;
  startTask();
}

/* ─── Textarea otomatik boyutlandırma ───────────────────── */
['task-input','input-area'].forEach(id => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener('input', () => {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, id === 'task-input' ? 260 : 180) + 'px';
  });
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      id === 'task-input' ? startTask() : sendMessage();
    }
  });
});

/* ─── Streaming durdur ──────────────────────────────────── */
function stopStreaming() {
  if (!isStreaming) return;
  if (chatSocket && chatSocket.readyState === WebSocket.OPEN) {
    chatSocket.send(JSON.stringify({ action: 'cancel' }));
  }
}

function connectWebSocket() {
  if (chatSocket && (chatSocket.readyState === WebSocket.OPEN || chatSocket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = localStorage.getItem('sidar_access_token') || '';
  const wsUrl = `${protocol}//${window.location.host}/ws/chat`;
  chatSocket = new WebSocket(wsUrl);


  chatSocket.onopen = () => {
    if (!token) {
      showAuthOverlay('Oturum bulunamadı. Lütfen giriş yapın.');
      chatSocket.close(1008, 'Authentication required');
      return;
    }
    chatSocket.send(JSON.stringify({ action: 'auth', token }));
  };

  chatSocket.onmessage = (event) => {
    let data = null;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }

    if (data.auth_ok) {
      return;
    }

    if (!currentStream) return;

    if (data.thought) {
      apSetThought(data.thought);
    }
    if (data.status) {
      apSetThought(data.status);
    }
    if (data.tool_call) {
      appendToolStep(currentStream.msgId, data.tool_call);
    }
    if (data.chunk !== undefined) {
      currentStream.accumulated += data.chunk;
      updateStreaming(currentStream.msgId, currentStream.accumulated);
    }
    if (data.done) {
      finishStreaming();
    }
  };

  chatSocket.onclose = () => {
    if (currentStream) {
      currentStream.accumulated += '\n\n*[Bağlantı kesildi. Yanıt tamamlanamadı.]*';
      finishStreaming();
    }
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWebSocket, 3000);
  };

  chatSocket.onerror = () => {
    showUiNotice('WebSocket bağlantı hatası oluştu.', 'warn');
  };
}

/* ─── Dosya ekleme ──────────────────────────────────────── */
function handleFileAttach(e) {
  const file = e.target.files[0];
  if (!file) return;
  if (file.size > 200 * 1024) {
    alert('Dosya boyutu 200 KB\'ı aşamaz.');
    e.target.value = '';
    return;
  }
  const reader = new FileReader();
  reader.onload = ev => {
    attachedFileContent = ev.target.result;
    attachedFileName    = file.name;
    renderAttachedFile(file.name);
  };
  reader.readAsText(file, 'utf-8');
  e.target.value = '';
}

function renderAttachedFile(name) {
  const preview = document.getElementById('attached-file-preview');
  preview.innerHTML = `
    <div class="attached-file">
      <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
        <path d="M4.5 3a2.5 2.5 0 0 1 5 0v9a1.5 1.5 0 0 1-3 0V5a.5.5 0 0 1 1 0v7a.5.5 0 0 0 1 0V3a1.5 1.5 0 1 0-3 0v9a2.5 2.5 0 0 0 5 0V5a.5.5 0 0 1 1 0v7a3.5 3.5 0 1 1-7 0V3z"/>
      </svg>
      <span>${escHtml(name)}</span>
      <button class="attached-file-remove" onclick="removeAttachedFile()" title="Dosyayı kaldır">✕</button>
    </div>`;
}

function removeAttachedFile() {
  attachedFileContent = null;
  attachedFileName    = null;
  document.getElementById('attached-file-preview').innerHTML = '';
}

/* ─── Mesaj gönderme ────────────────────────────────────── */
function sendMessage() {
  const textarea = document.getElementById('input-area');
  const text = textarea.value.trim();
  if (!text && !attachedFileContent) return;
  const finalText = attachedFileContent
    ? `${text}\n\n**Dosya: ${attachedFileName}**\n\`\`\`\n${attachedFileContent}\n\`\`\``
    : text;
  textarea.value = '';
  textarea.style.height = 'auto';
  removeAttachedFile();
  sendText(finalText);
}

async function sendText(text) {
  if (isStreaming) return;
  if (!chatSocket || chatSocket.readyState !== WebSocket.OPEN) {
    connectWebSocket();
    showUiNotice('Sunucu bağlantısı hazırlanıyor, lütfen tekrar deneyin.', 'warn');
    return;
  }

  isStreaming = true;
  const sendBtn = document.getElementById('send-btn');
  const stopBtn = document.getElementById('stop-btn');
  if (sendBtn) { sendBtn.disabled = true; sendBtn.style.display = 'none'; }
  if (stopBtn) stopBtn.style.display = 'flex';

  apShow();
  appendUser(text);
  const msgId = createSidarMsg();
  currentStream = { msgId, accumulated: '' };

  try {
    chatSocket.send(JSON.stringify({ message: text }));
  } catch (err) {
    currentStream.accumulated = `[Bağlantı Hatası: ${err.message}]`;
    finishStreaming();
  }
}

function finishStreaming() {
  if (!currentStream) return;
  const sendBtn = document.getElementById('send-btn');
  const stopBtn = document.getElementById('stop-btn');

  finalizeMsg(currentStream.msgId, currentStream.accumulated);
  currentStream = null;
  isStreaming = false;

  if (sendBtn) { sendBtn.disabled = false; sendBtn.style.display = ''; }
  if (stopBtn) stopBtn.style.display = 'none';

  apDone();
  loadSessions();
}

/* ─── Mesaj yardımcıları ────────────────────────────────── */
function escHtml(str) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(str));
  return d.innerHTML;
}


function sanitizeRenderedHtml(html) {
  const template = document.createElement('template');
  template.innerHTML = html;

  const blockedTags = new Set(['script', 'iframe', 'object', 'embed', 'form', 'meta', 'link']);
  template.content.querySelectorAll('*').forEach(node => {
    const tag = node.tagName.toLowerCase();
    if (blockedTags.has(tag)) {
      node.remove();
      return;
    }

    for (const attr of [...node.attributes]) {
      const name = attr.name.toLowerCase();
      const value = (attr.value || '').trim().toLowerCase();
      if (name.startsWith('on')) {
        node.removeAttribute(attr.name);
        continue;
      }
      const isUrlAttr = name === 'href' || name === 'src' || name === 'xlink:href';
      if (isUrlAttr && (value.startsWith('javascript:') || value.startsWith('data:text/html'))) {
        node.removeAttribute(attr.name);
      }
    }
  });

  return template.innerHTML;
}

function scrollBottom() {
  const msgs = document.getElementById('messages');
  msgs.scrollTop = msgs.scrollHeight;
}

function appendUser(text) {
  const msgs = document.getElementById('messages');
  const el = document.createElement('div');
  el.className = 'message message-user';
  const safeText = escHtml(text);
  el.innerHTML = `
    <div class="msg-header">
      <div class="msg-avatar avatar-user">S</div>
      <span>Sen</span>
    </div>
    <div class="msg-body" style="white-space:pre-wrap">${safeText}</div>
    <div class="msg-actions">
      <button class="msg-action-btn" onclick="editMessage(this, ${JSON.stringify(text)})" title="Düzenle ve tekrar gönder">
        ✏ Düzenle
      </button>
      <button class="msg-action-btn" onclick="copyText(${JSON.stringify(text)}, this)" title="Mesajı kopyala">
        📋 Kopyala
      </button>
    </div>`;
  msgs.appendChild(el);
  scrollBottom();
}

function editMessage(btn, originalText) {
  // Kullanıcı mesaj balonunu DOM'dan kaldır (tekrar gönderiş temiz olsun)
  const msgEl = btn.closest('.message');
  if (msgEl) msgEl.remove();

  const inputArea = document.getElementById('input-area');
  inputArea.value = originalText;
  inputArea.style.height = 'auto';
  inputArea.style.height = Math.min(inputArea.scrollHeight, 180) + 'px';
  inputArea.focus();
}

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = '✓ Kopyalandı';
    setTimeout(() => btn.textContent = orig, 1500);
  });
}

function createSidarMsg() {
  const msgs = document.getElementById('messages');
  const id   = `m${++msgCounter}`;
  const el   = document.createElement('div');
  el.className = 'message message-sidar';
  el.id = id;
  el.innerHTML = `
    <div class="msg-header">
      <div class="msg-avatar avatar-sidar">SI</div>
      <span>Sidar</span>
    </div>
    <div class="tool-activity" id="${id}-tools"></div>
    <div class="msg-body">
      <span class="streaming-text" id="${id}-txt"></span><span class="cursor" id="${id}-cur"></span>
    </div>`;
  msgs.appendChild(el);
  scrollBottom();
  return id;
}

function updateStreaming(id, rawText) {
  const span = document.getElementById(`${id}-txt`);
  if (span) span.textContent = rawText;
  scrollBottom();
}

function finalizeMsg(id, rawText) {
  const el = document.getElementById(id);
  if (!el) return;
  const body   = el.querySelector('.msg-body');
  const cursor = document.getElementById(`${id}-cur`);
  if (cursor) cursor.remove();
  body.innerHTML = sanitizeRenderedHtml(marked.parse(rawText || '*(yanıt alınamadı)*'));
  body.querySelectorAll('pre code').forEach(b => hljs.highlightElement(b));

  // Kod bloklarına kopyala butonu ekle
  body.querySelectorAll('pre').forEach(pre => {
    const wrap = document.createElement('div');
    wrap.className = 'code-wrap';
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.innerHTML = `<svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor"><path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z"/><path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"/></svg> Kopyala`;
    btn.onclick = () => {
      const code = pre.querySelector('code');
      navigator.clipboard.writeText(code ? code.innerText : pre.innerText).then(() => {
        btn.textContent = '✓ Kopyalandı';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.innerHTML = `<svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor"><path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z"/><path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"/></svg> Kopyala`;
          btn.classList.remove('copied');
        }, 2000);
      });
    };
    wrap.appendChild(btn);
  });

  scrollBottom();
}

/* ─── Tool Activity (ReAct adım göstergesi) ─────────────── */
const TOOL_LABELS = {
  // Dosya işlemleri
  list_dir:             '📂 Dizin listeleniyor',
  read_file:            '📄 Dosya okunuyor',
  write_file:           '✏️ Dosya yazılıyor',
  patch_file:           '🔧 Dosya güncelleniyor',
  glob_search:          '🔍 Dosyalar aranıyor',
  grep_files:           '🔍 Dosya içeriği taranıyor',
  grep:                 '🔍 Dosya içeriği taranıyor',
  // Kod çalıştırma
  execute_code:         '⚡ Kod çalıştırılıyor',
  run_shell:            '💻 Kabuk komutu çalıştırılıyor',
  bash:                 '💻 Kabuk komutu çalıştırılıyor',
  shell:                '💻 Kabuk komutu çalıştırılıyor',
  ls:                   '📂 Dizin listeleniyor',
  // Alt görev & Paralel (Agent tool eşdeğeri)
  subtask:              '🤖 Alt görev çalıştırılıyor',
  agent:                '🤖 Alt ajan başlatılıyor',
  parallel:             '⚡ Paralel araçlar çalıştırılıyor',
  // Sistem
  audit:                '🔍 Proje denetleniyor',
  health:               '💻 Sistem kontrol ediliyor',
  gpu_optimize:         '🎮 GPU optimize ediliyor',
  get_config:           '⚙️ Yapılandırma okunuyor',
  print_config_summary: '⚙️ Yapılandırma okunuyor',
  // Görev takibi
  todo_write:           '📝 Görev listesi güncelleniyor',
  todo_read:            '📋 Görev listesi okunuyor',
  todo_update:          '✅ Görev güncelleniyor',
  // GitHub — depo
  github_commits:       '📋 GitHub commit\'leri okunuyor',
  github_info:          'ℹ️ GitHub bilgisi alınıyor',
  github_read:          '📖 GitHub dosyası okunuyor',
  github_list_files:    '📂 GitHub dosyaları listeleniyor',
  github_write:         '✏️ GitHub\'a dosya yazılıyor',
  github_create_branch: '🌿 Yeni dal oluşturuluyor',
  github_search_code:   '🔍 GitHub\'da kod aranıyor',
  // GitHub — PR yönetimi
  github_create_pr:     '🔀 Pull Request oluşturuluyor',
  github_smart_pr:      '✨ Akıllı PR oluşturuluyor',
  github_list_prs:      '🔀 PR listesi alınıyor',
  github_get_pr:        '🔀 PR detayı okunuyor',
  github_comment_pr:    '💬 PR\'a yorum ekleniyor',
  github_close_pr:      '🚪 PR kapatılıyor',
  github_pr_files:      '📁 PR dosyaları listeleniyor',
  // Web & Paket
  web_search:           '🌐 Web\'de aranıyor',
  fetch_url:            '🔗 URL getiriliyor',
  search_docs:          '📚 Belgeler aranıyor',
  search_stackoverflow: '🤔 Stack Overflow aranıyor',
  pypi:                 '📦 PyPI sorgulanıyor',
  pypi_compare:         '📦 PyPI paketleri karşılaştırılıyor',
  npm:                  '📦 npm sorgulanıyor',
  gh_releases:          '🚀 GitHub sürümleri alınıyor',
  gh_latest:            '🚀 Son sürüm sorgulanıyor',
  // RAG
  docs_search:          '📚 Dokümantasyon aranıyor',
  docs_add:             '📝 Belge ekleniyor',
  docs_add_file:        '📁 Dosya RAG\'a ekleniyor',
  docs_list:            '📋 Belgeler listeleniyor',
  docs_delete:          '🗑️ Belge siliniyor',
};

function appendToolStep(msgId, toolName) {
  const container = document.getElementById(`${msgId}-tools`);
  if (!container) return;
  const label = TOOL_LABELS[toolName] || `🔧 ${toolName}`;
  const step = document.createElement('div');
  step.className = 'tool-step';
  step.textContent = label;
  container.appendChild(step);
  scrollBottom();
  apAddTool(toolName, label);  // Activity Panel'i güncelle
}

/* ─── Activity Panel (Canlı Arka Plan Aktivitesi) ────────── */
let _apVisible      = false;
let _apStartTime    = 0;
let _apTimerInt     = null;
let _apTodoPollInt  = null;
let _apLastToolEl   = null;   // Feed'deki son araç satırı (tamamlandı işareti için)
let _apDoneTimeout  = null;

function apShow() {
  const panel = document.getElementById('activity-panel');
  if (!panel) return;
  // Durumu sıfırla
  document.getElementById('ap-feed').innerHTML       = '';
  document.getElementById('ap-thought').style.display  = 'none';
  document.getElementById('ap-current').style.display  = 'none';
  document.getElementById('ap-todo-section').style.display = 'none';
  document.getElementById('ap-title-text').textContent = 'Sidar Çalışıyor…';
  document.getElementById('ap-timer').textContent      = '0s';
  const sp = document.getElementById('ap-spinner');
  if (sp) { sp.classList.remove('ap-done'); }
  _apLastToolEl = null;
  if (_apDoneTimeout) { clearTimeout(_apDoneTimeout); _apDoneTimeout = null; }

  _apStartTime = Date.now();
  _apVisible   = true;
  panel.classList.add('ap-visible');

  // Topbar toggle butonunu göster
  const btn = document.getElementById('ap-toggle-btn');
  if (btn) btn.classList.add('ap-btn-active');

  // Saniye sayacı
  if (_apTimerInt) clearInterval(_apTimerInt);
  _apTimerInt = setInterval(() => {
    const el = document.getElementById('ap-timer');
    if (el) el.textContent = Math.floor((Date.now() - _apStartTime) / 1000) + 's';
  }, 1000);

  // Todo listesini 2 saniyede bir güncelle (ajan todo_write kullanıyorsa)
  if (_apTodoPollInt) clearInterval(_apTodoPollInt);
  _apTodoPollInt = setInterval(apRefreshTodos, 2000);
}

function apHide() {
  const panel = document.getElementById('activity-panel');
  if (panel) panel.classList.remove('ap-visible');
  _apVisible = false;
  const btn = document.getElementById('ap-toggle-btn');
  if (btn) btn.classList.remove('ap-btn-active');
  if (_apTimerInt)    { clearInterval(_apTimerInt);    _apTimerInt    = null; }
  if (_apTodoPollInt) { clearInterval(_apTodoPollInt); _apTodoPollInt = null; }
}

function apToggle() {
  const panel = document.getElementById('activity-panel');
  if (!panel) return;
  if (panel.classList.contains('ap-visible')) {
    panel.classList.remove('ap-visible');
  } else {
    panel.classList.add('ap-visible');
  }
}

function apDone() {
  // Önceki aracı tamamlandı olarak işaretle
  if (_apLastToolEl) {
    const icon = _apLastToolEl.querySelector('.ap-feed-icon');
    if (icon) icon.textContent = '✅';
    _apLastToolEl.classList.add('ap-item-done');
    _apLastToolEl = null;
  }
  // Aktif araç göstergesini gizle
  const cur = document.getElementById('ap-current');
  if (cur) cur.style.display = 'none';
  // Başlığı güncelle
  const titleEl = document.getElementById('ap-title-text');
  if (titleEl) titleEl.textContent = '✓ Tamamlandı';
  const sp = document.getElementById('ap-spinner');
  if (sp) sp.classList.add('ap-done');
  // Zamanlayıcıları durdur
  if (_apTimerInt)    { clearInterval(_apTimerInt);    _apTimerInt    = null; }
  if (_apTodoPollInt) { clearInterval(_apTodoPollInt); _apTodoPollInt = null; }
  // Son todo durumunu çek
  apRefreshTodos();
  // 5 saniye sonra otomatik kapat
  _apDoneTimeout = setTimeout(() => apHide(), 5000);
}

function apSetThought(text) {
  const box  = document.getElementById('ap-thought');
  const span = document.getElementById('ap-thought-text');
  if (!box || !span) return;
  span.textContent = text;
  box.style.display = 'flex';
}

function apAddTool(toolName, label) {
  // Önceki aracı tamamlandı işaretle
  if (_apLastToolEl) {
    const icon = _apLastToolEl.querySelector('.ap-feed-icon');
    if (icon) icon.textContent = '✅';
    _apLastToolEl.classList.add('ap-item-done');
  }
  // Aktif araç satırını güncelle
  const cur      = document.getElementById('ap-current');
  const curLabel = document.getElementById('ap-current-label');
  if (cur && curLabel) {
    curLabel.textContent = label;
    cur.style.display = 'flex';
  }
  // Feed'e yeni satır ekle
  const feed = document.getElementById('ap-feed');
  if (!feed) return;
  const item = document.createElement('div');
  item.className = 'ap-feed-item';
  item.innerHTML = `<span class="ap-feed-icon">⏳</span><span class="ap-feed-text">${label}</span>`;
  feed.appendChild(item);
  feed.scrollTop = feed.scrollHeight;
  _apLastToolEl = item;
}

async function apRefreshTodos() {
  try {
    const data = await (await fetchAPI('/todo')).json();
    const tasks = data.tasks || [];
    if (!tasks.length) return;
    const section = document.getElementById('ap-todo-section');
    const list    = document.getElementById('ap-todo-items');
    if (!section || !list) return;
    section.style.display = 'block';
    const STATUS_ICON = { pending: '⬜', in_progress: '🔄', completed: '✅' };
    const order = ['in_progress', 'pending', 'completed'];
    const sorted = [...tasks].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status));
    list.innerHTML = sorted.map(t => {
      const cls = t.status === 'in_progress' ? 'ap-todo-ip'
                : t.status === 'completed'   ? 'ap-todo-done' : '';
      return `<div class="ap-todo-item">
        <span class="ap-todo-icon">${STATUS_ICON[t.status] || '⬜'}</span>
        <span class="ap-todo-text ${cls}">${t.content}</span>
      </div>`;
    }).join('');
  } catch { /* sessizce geç */ }
}

/* ─── Todo Panel (Claude Code TodoWrite uyumlu) ─────────── */
let _todoPollTimer = null;

function toggleTodoPanel() {
  const panel = document.getElementById('todo-panel');
  if (panel.classList.contains('visible')) {
    panel.classList.remove('visible');
  } else {
    panel.classList.add('visible');
    fetchTodo();
  }
}

function closeTodoPanel() {
  document.getElementById('todo-panel').classList.remove('visible');
}

async function fetchTodo() {
  try {
    const data = await (await fetchAPI('/todo')).json();
    renderTodoPanel(data.tasks || []);
    updateTodoIndicator(data.active || 0);
  } catch { /* bağlantı yok — sessizce geç */ }
}

function renderTodoPanel(tasks) {
  const body = document.getElementById('todo-body');
  if (!tasks.length) {
    body.innerHTML = '<div class="todo-empty">Henüz görev yok</div>';
    return;
  }

  const STATUS_ICON = { pending: '⬜', in_progress: '🔄', completed: '✅' };
  const order = ['in_progress', 'pending', 'completed'];
  const sorted = [...tasks].sort((a, b) =>
    order.indexOf(a.status) - order.indexOf(b.status)
  );

  body.innerHTML = sorted.map(t => {
    const cls = t.status === 'in_progress' ? 'in-progress'
              : t.status === 'completed'   ? 'completed' : '';
    return `<div class="todo-item">
      <span class="todo-icon">${STATUS_ICON[t.status] || '⬜'}</span>
      <span class="todo-text ${cls}">${t.content}</span>
    </div>`;
  }).join('');

  // Panelin rozet sayısını güncelle
  const active = tasks.filter(t => t.status !== 'completed').length;
  document.getElementById('todo-badge').textContent = active || tasks.length;
}

function updateTodoIndicator(activeCount) {
  const ind = document.getElementById('todo-indicator');
  const txt = document.getElementById('todo-indicator-text');
  if (activeCount > 0) {
    ind.classList.add('active');
    txt.textContent = `${activeCount} görev`;
  } else {
    ind.classList.remove('active');
  }
}

function startTodoPoll() {
  stopTodoPoll();
  fetchTodo(); // Hemen bir kez al
  _todoPollTimer = setInterval(fetchTodo, 5000);
}

function stopTodoPoll() {
  if (_todoPollTimer) { clearInterval(_todoPollTimer); _todoPollTimer = null; }
}

// Sayfa yüklendiğinde polling başlat
window.addEventListener('load', () => { connectWebSocket(); setTimeout(startTodoPoll, 1500); });